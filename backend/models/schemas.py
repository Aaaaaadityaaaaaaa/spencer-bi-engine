from typing import List, Dict, Any, Optional, Literal, Union
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
    strategy: Literal["zero", "mean", "median", "custom"]
    fill_value: Optional[Any] = None

class TransformCast(BaseModel):
    op: Literal["cast"]
    column: str
    new_type: str

class TransformCalculatedColumn(BaseModel):
    op: Literal["calculated_column"]
    new_column_name: str
    formula: str

TransformParam = Union[
    TransformDedupe,
    TransformDropNull,
    TransformImputeNull,
    TransformCast,
    TransformCalculatedColumn
]

class TransformResponse(BaseModel):
    schema_version: int
    step: int
    row_count: int

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
