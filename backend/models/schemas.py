from typing import List, Dict, Any, Optional, Literal, Union, Annotated
from pydantic import BaseModel, Field

class ColumnSchema(BaseModel):
    name: str
    type: str
    cardinality: int

class SessionResponse(BaseModel):
    session_uuid: str
    table_name: str
    row_count: int
    columns: List[ColumnSchema]

class TableUploadResponse(BaseModel):
    table_name: str
    row_count: int
    columns: List[ColumnSchema]

class TableSchemaResponse(BaseModel):
    table_name: str
    is_primary: bool
    columns: List[ColumnSchema]

class SchemaResponse(BaseModel):
    tables: List[TableSchemaResponse]

# Transform Op Schemas
class TransformDedupe(BaseModel):
    op: Literal["dedupe"]

class TransformDropNull(BaseModel):
    op: Literal["drop_null"]
    column: str

class TransformImputeNull(BaseModel):
    op: Literal["impute_null"]
    column: str
    # `mode` (TASK-005) is the most-frequent non-null value -- the only non-custom
    # option that also works for a categorical/text column (mean/median are numeric).
    strategy: Literal["zero", "mean", "median", "mode", "custom"]
    fill_value: Optional[Any] = None

class TransformCast(BaseModel):
    op: Literal["cast"]
    column: str
    new_type: str

class TransformCalculatedColumn(BaseModel):
    op: Literal["calculated_column"]
    new_column_name: str
    formula: str

# --- TASK-005 ops -----------------------------------------------------------
class TransformDropColumn(BaseModel):
    op: Literal["drop_column"]
    column: str

class TransformRenameColumn(BaseModel):
    op: Literal["rename_column"]
    column: str
    new_name: str

class TransformDedupeSubset(BaseModel):
    op: Literal["dedupe_subset"]
    columns: List[str]
    keep: Literal["first", "last"] = "first"

class TransformStringNormalize(BaseModel):
    op: Literal["string_normalize"]
    column: str
    trim: bool = False
    case: Optional[Literal["upper", "lower", "capitalize"]] = None
    find: Optional[str] = None
    replace: Optional[str] = None
    null_token: Optional[str] = None

class TransformFilterRows(BaseModel):
    op: Literal["filter_rows"]
    # A user-authored boolean predicate (e.g. "revenue > 0"). Runs on the
    # non-sandboxed path, so it is validated by the SAME fail-closed scalar
    # validator as calculated_column (see transform_service._validate_formula).
    predicate: str
    action: Literal["keep", "remove"] = "keep"

# Discriminated on `op` so FastAPI/Pydantic route each payload to exactly one
# model (e.g. drop_null vs impute_null, which share a `column` field).
TransformParam = Annotated[
    Union[
        TransformDedupe,
        TransformDropNull,
        TransformImputeNull,
        TransformCast,
        TransformCalculatedColumn,
        TransformDropColumn,
        TransformRenameColumn,
        TransformDedupeSubset,
        TransformStringNormalize,
        TransformFilterRows,
    ],
    Field(discriminator="op"),
]

class TransformResponse(BaseModel):
    schema_version: int
    step: int
    row_count: int

class PreviewColumn(BaseModel):
    name: str
    type: str

class TransformPreviewResponse(BaseModel):
    """Dry-run result (TASK-005): what a transform *would* do, computed by running
    only SELECTs -- no materialize, no snapshot, no history step, no version bump."""
    op: str
    row_count_before: int
    row_count_after: int
    row_count_delta: int
    columns: List[PreviewColumn]
    sample: List[Dict[str, Any]]
    compiled_sql: str

class HistoryStep(BaseModel):
    step: int
    op: str
    column: Optional[str] = None
    timestamp: str

class HistoryResponse(BaseModel):
    steps: List[HistoryStep]
    current_step_index: int
    total_steps: int
    can_undo: bool
    can_redo: bool

class ChartRequest(BaseModel):
    x_axis: str
    y_axis: str
    aggregation: str
    chart_type: str

class AskRequest(BaseModel):
    question: str

class AskResponse(BaseModel):
    sql: str
    cache_hit: bool
    retries_used: int

class ExecuteRequest(BaseModel):
    sql: str

class ExecuteResponse(BaseModel):
    query_id: str
    status: Literal["running", "completed", "failed", "cancelled"]

class QueryPollResponse(BaseModel):
    status: Literal["running", "completed", "failed", "cancelled"]
    result: Optional[bytes] = None  # MessagePack ref
    error: Optional[str] = None

class CustomInstruction(BaseModel):
    term: str
    definition: str

class ScheduleRequest(BaseModel):
    question: str
    cron: str

class ScheduleResponse(BaseModel):
    schedule_id: str
    next_run: str

class ErrorResponse(BaseModel):
    error: str
    message: str
    retryable: bool
