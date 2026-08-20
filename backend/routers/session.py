import uuid
import os
import shutil
import re
from fastapi import APIRouter, UploadFile, File, HTTPException
from models.schemas import (
    SessionResponse,
    SchemaResponse,
    TableUploadResponse,
    TableSchemaResponse,
    TransformParam,
    TransformResponse,
    HistoryResponse,
    ColumnSchema
)
from services.duckdb_manager import db_manager
from services.redis_manager import redis_manager

router = APIRouter()

def sanitize_table_name(name: str) -> str:
    clean = re.sub(r'\W', '_', name)
    clean = re.sub(r'^_+|_+$', '', clean)
    if not clean or clean[0].isdigit():
        clean = "t_" + clean
    return clean.lower()

def _safe_disk_name(clean_name: str, original_filename: str) -> str:
    """A filesystem-safe upload name. `clean_name` is already \\W-sanitized; we
    keep only the original extension and strip anything that could enable path
    traversal or SQL-string breakout from the extension."""
    ext = os.path.splitext(original_filename)[1]
    return re.sub(r'[^A-Za-z0-9._-]', '_', f"{clean_name}{ext}")

def _table_name_for(session_uuid: str, filename: str):
    base_name = os.path.splitext(filename)[0]
    clean_name = sanitize_table_name(base_name)
    return f"t_{session_uuid.replace('-', '_')}_{clean_name}", clean_name

def _persist_upload(session_uuid: str, file: UploadFile, clean_name: str) -> str:
    os.makedirs(f"uploads/{session_uuid}", exist_ok=True)
    file_path = f"uploads/{session_uuid}/{_safe_disk_name(clean_name, file.filename)}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return file_path

def _quote_ident(name: str) -> str:
    """Double-quote a SQL identifier, escaping embedded quotes (column names
    come from CSV headers, which are not trusted)."""
    return '"' + name.replace('"', '""') + '"'

async def analyze_and_register_table(session_uuid: str, table_name: str, file_path: str, is_primary: bool):
    # Load into duckdb. The file path is BOUND as a parameter (never interpolated)
    # so a crafted filename cannot break out of the read_csv_auto string literal.
    # table_name is a \\W-sanitized identifier, safe to interpolate.
    await db_manager.run_readwrite(
        f"CREATE TABLE {table_name} AS SELECT * FROM read_csv_auto(?, header=true)",
        (file_path,),
    )

    row_count = (await db_manager.run_readwrite(f"SELECT COUNT(*) FROM {table_name}"))[0][0]

    col_info = await db_manager.run_readwrite(f"PRAGMA table_info({table_name})")
    columns = []

    table_schema_context = {
        "cardinality": {},
        "samples": {},
        "is_primary": is_primary
    }

    ddl_parts = []

    for row in col_info:
        col_name = row[1]
        col_type = row[2]
        qcol = _quote_ident(col_name)

        card_res = await db_manager.run_readwrite(f'SELECT COUNT(DISTINCT {qcol}) FROM {table_name}')
        cardinality = card_res[0][0] if card_res else 0

        columns.append(ColumnSchema(name=col_name, type=col_type, cardinality=cardinality))

        table_schema_context["cardinality"][col_name] = cardinality
        ddl_parts.append(f'{qcol} {col_type}')

        if cardinality < 20 and cardinality > 0:
            samples_res = await db_manager.run_readwrite(
                f'SELECT DISTINCT {qcol} FROM {table_name} WHERE {qcol} IS NOT NULL LIMIT 20'
            )
            samples = [s[0] for s in samples_res]
            table_schema_context["samples"][col_name] = samples

    table_schema_context["ddl"] = f"CREATE TABLE {table_name} ({', '.join(ddl_parts)});"

    schema_key = f"schema:{session_uuid}"
    schema_data = redis_manager.get_json(schema_key) or {}
    schema_data[table_name] = table_schema_context
    redis_manager.set_json(schema_key, schema_data)

    return row_count, columns

@router.post("", response_model=SessionResponse)
async def create_session(file: UploadFile = File(...)):
    session_uuid = str(uuid.uuid4())
    table_name, clean_name = _table_name_for(session_uuid, file.filename)
    file_path = _persist_upload(session_uuid, file, clean_name)

    row_count, columns = await analyze_and_register_table(session_uuid, table_name, file_path, is_primary=True)

    return SessionResponse(
        session_uuid=session_uuid,
        table_name=table_name,
        row_count=row_count,
        columns=columns
    )

@router.post("/{session_uuid}/tables", response_model=TableUploadResponse)
async def upload_table(session_uuid: str, file: UploadFile = File(...)):
    table_name, clean_name = _table_name_for(session_uuid, file.filename)

    # Refuse to overwrite an existing table in this session (no silent clobber).
    existing = redis_manager.get_json(f"schema:{session_uuid}") or {}
    if table_name in existing:
        raise HTTPException(
            status_code=409,
            detail=f"Table '{table_name}' already exists in this session"
        )

    file_path = _persist_upload(session_uuid, file, clean_name)

    row_count, columns = await analyze_and_register_table(session_uuid, table_name, file_path, is_primary=False)

    return TableUploadResponse(
        table_name=table_name,
        row_count=row_count,
        columns=columns
    )

@router.get("/{session_uuid}/schema", response_model=SchemaResponse)
async def get_schema(session_uuid: str):
    schema_key = f"schema:{session_uuid}"
    schema_data = redis_manager.get_json(schema_key)
    if not schema_data:
        raise HTTPException(status_code=404, detail="Schema not found")

    tables = []
    for t_name, t_data in schema_data.items():
        col_info = await db_manager.run_readwrite(f"PRAGMA table_info({t_name})")
        cols = []
        for row in col_info:
            c_name = row[1]
            c_type = row[2]
            c_card = t_data["cardinality"].get(c_name, 0)
            cols.append(ColumnSchema(name=c_name, type=c_type, cardinality=c_card))

        tables.append(TableSchemaResponse(
            table_name=t_name,
            is_primary=t_data.get("is_primary", False),
            columns=cols
        ))

    return SchemaResponse(tables=tables)

@router.delete("/{session_uuid}")
async def delete_session(session_uuid: str):
    # Teardown session, drop tables, clear Redis keys
    return {"status": "deleted"}

@router.post("/{session_uuid}/transform", response_model=TransformResponse)
async def apply_transform(session_uuid: str, payload: TransformParam):
    # Apply one transform op
    return TransformResponse(schema_version=1, step=1, row_count=0)

@router.post("/{session_uuid}/undo", response_model=TransformResponse)
async def undo_transform(session_uuid: str):
    # Revert to previous snapshot
    return TransformResponse(schema_version=1, step=0, row_count=0)

@router.post("/{session_uuid}/redo", response_model=TransformResponse)
async def redo_transform(session_uuid: str):
    # Reapply a reverted snapshot
    return TransformResponse(schema_version=1, step=1, row_count=0)

@router.get("/{session_uuid}/history", response_model=HistoryResponse)
async def get_history(session_uuid: str):
    # List transform step history + undo/redo state
    return HistoryResponse(
        steps=[],
        current_step_index=0,
        total_steps=0,
        can_undo=False,
        can_redo=False
    )
