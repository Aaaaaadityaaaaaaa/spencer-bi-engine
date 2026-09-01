from typing import List, Dict, Any, Optional, Literal, Union, Annotated
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

# --- Auth & multi-tenancy (TASK-027) -------------------------------------
# EmailStr requires the `email-validator` package (pulled in via pydantic[email]).
# Password bounded at 72 bytes' worth of chars up top: bcrypt only considers the
# first 72 *bytes*, so anything longer is silently ignored by the hash anyway --
# we cap here for a clear 422 instead of a surprising truncation. min_length 8 is
# a light floor, not a policy engine (out of scope this wave).
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)

class UserResponse(BaseModel):
    id: int
    email: str = Field(..., max_length=255)
    is_admin: bool
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ColumnSchema(BaseModel):
    name: str = Field(..., max_length=255)
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
    # TASK-041 #4: round a computed mean/median fill to this many decimal places
    # (ignored for zero/mode/custom). None => no rounding (raw mean/median).
    decimals: Optional[int] = Field(None, ge=0, le=10)

class TransformCast(BaseModel):
    op: Literal["cast"]
    column: str
    new_type: str
    # When true, un-parseable values are set to NULL (TRY_CAST) instead of failing
    # the whole cast. Default false preserves the strict CAST behavior (TASK-017).
    coerce: bool = False

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
    # --- TASK-018 text-toolkit extensions (all optional => backward-compatible) --
    # When true, `find` is a regex and replace uses REGEXP_REPLACE (global) instead
    # of a literal replace. `strip_special` removes every non-alphanumeric char
    # (spaces kept). `pad_*` left/right-pads to `pad_length` with a single `pad_char`.
    regex: bool = False
    strip_special: bool = False
    # TASK-041 #3/#6: collapse internal runs of whitespace to a single space and
    # trim the ends -- merges " u . p . i " / "u.p.i" style spacing variants so
    # near-duplicate categories fold together. Applied after trim/case.
    collapse_whitespace: bool = False
    pad_side: Optional[Literal["left", "right"]] = None
    pad_length: Optional[int] = None
    pad_char: Optional[str] = None

# --- TASK-018 derive ops (add a new column from one source column) ----------
class TransformSplitColumn(BaseModel):
    """Split / extract into a NEW column from one text source column.
    delimiter mode: take the `index`-th field (0-based) of column split on
    `delimiter` (out-of-range => NULL). regex mode: take capture `group`
    (0 = whole match) of `pattern`. Compiled via Ibis .split()[i] / .re_extract()."""
    op: Literal["split_column"]
    column: str
    new_column_name: str
    mode: Literal["delimiter", "regex"] = "delimiter"
    delimiter: Optional[str] = None
    index: int = 0
    pattern: Optional[str] = None
    group: int = 0

class TransformDateExtract(BaseModel):
    """Derive a NEW column from a DATE/TIMESTAMP source. `part` mode extracts a
    calendar component (year/month/.../weekday_name); hour/minute/second require a
    TIMESTAMP source. `format` mode reformats via strftime(`date_format`)."""
    op: Literal["date_extract"]
    column: str
    new_column_name: str
    mode: Literal["part", "format"] = "part"
    part: Optional[Literal[
        "year", "month", "day", "quarter", "dayofyear",
        "weekday", "weekday_name", "hour", "minute", "second",
    ]] = None
    date_format: Optional[str] = None

class TransformBinColumn(BaseModel):
    """Bin a numeric source column into a NEW integer bin-index column (0-based).
    equal_width => Ibis .histogram(nbins) (equal-width ranges); quantile =>
    .ntile(bins) (equal-count buckets). `bins` is range-checked (2..50) in the
    service so an out-of-range value fails closed as a 400, not a 422."""
    op: Literal["bin_column"]
    column: str
    new_column_name: str
    method: Literal["equal_width", "quantile"] = "equal_width"
    bins: int = 5

# --- TASK-019 (Wave 1b) ordered-window ops ----------------------------------
class TransformFillDown(BaseModel):
    """Forward/backward-fill nulls in a column using the last/next non-null value
    in stable row order. Unlike the set-based Ibis ops, this needs an ORDERED
    window, so it compiles to raw SQL over DuckDB's ``rowid`` (see
    transform_service._build_filldown_sql). `direction` "down" carries the last
    non-null value forward; "up" carries the next non-null value backward."""
    op: Literal["fill_down"]
    column: str
    direction: Literal["down", "up"] = "down"

class TransformFlagOutliers(BaseModel):
    """Add a NEW boolean column flagging statistical outliers in a numeric source
    column. `method` "zscore" flags rows whose value is more than `threshold`
    standard deviations from the column mean (full-frame window stats). `threshold`
    is range-checked (> 0) in the service so a bad value fails closed as a 400."""
    op: Literal["flag_outliers"]
    column: str
    new_column_name: str
    method: Literal["zscore"] = "zscore"
    threshold: float = 3.0

class TransformFilterRows(BaseModel):
    op: Literal["filter_rows"]
    # A user-authored boolean predicate (e.g. "revenue > 0"). Runs on the
    # non-sandboxed path, so it is validated by the SAME fail-closed scalar
    # validator as calculated_column (see transform_service._validate_formula).
    predicate: str
    action: Literal["keep", "remove"] = "keep"

class TransformUpdateCell(BaseModel):
    """TASK-041 #5: in-cell edit -- set ONE cell (identified by its stable DuckDB
    ``rowid``, the same anchor /data pages by) to a new value. `value=None` clears the
    cell to NULL; otherwise the value is CAST to the column's type in compiled SQL, so
    a value that can't parse fails closed as a 400. Undoable like any other transform
    (it snapshots + records a history step). Only `column` + `rowid` are interpolated,
    both validated/quoted server-side; the value never reaches SQL as raw text."""
    op: Literal["update_cell"]
    column: str
    rowid: int
    value: Optional[Any] = None

class TransformAbsoluteValue(BaseModel):
    """TASK-042: replace a numeric column with its absolute value (drop the negative
    sign) IN PLACE. Offered as the alternative one-click fix on the ``negative_values``
    quality finding -- "make positive" instead of dropping the rows. Compiled via Ibis
    ``t.mutate(col=col.abs())`` (ADR-012); rejected for a non-numeric column. Undoable
    like any transform (snapshots + records a history step)."""
    op: Literal["absolute_value"]
    column: str

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
        TransformSplitColumn,
        TransformDateExtract,
        TransformBinColumn,
        TransformFillDown,
        TransformFlagOutliers,
        TransformFilterRows,
        TransformUpdateCell,
        TransformAbsoluteValue,
    ],
    Field(discriminator="op"),
]

class TransformResponse(BaseModel):
    schema_version: int
    step: int
    row_count: int

class PreviewColumn(BaseModel):
    name: str = Field(..., max_length=255)
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
    # Only set for a coercing cast (op=="cast", coerce=true): how many currently
    # non-null values would be set to NULL because they can't parse (TASK-017).
    coerced_null_count: Optional[int] = None

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

# --- Data grid (Phase 4 / TASK-006) -----------------------------------------
class DataResponse(BaseModel):
    """A windowed read of a session table for the virtualized grid. JSON (not
    MessagePack): a grid read stays debuggable; MessagePack remains the house
    style for large analytical results (/execute, /chart). `columns` reuses
    PreviewColumn {name,type}; `rows` mirrors TransformPreviewResponse.sample."""
    columns: List[PreviewColumn]
    rows: List[Dict[str, Any]]
    total: int
    offset: int
    limit: int
    # Heatmap colour-scale support (TASK-022): whole-table [min, max] per numeric
    # column, sent only on the first window (offset == 0) and cached client-side.
    # None when the window isn't the first page or the table has no numeric column.
    ranges: Optional[Dict[str, List[float]]] = None
    # TASK-041 #5: the DuckDB rowid for each row in `rows` (parallel array), so the
    # grid can target an exact cell for in-cell editing regardless of sort/search.
    # None on legacy/empty reads; present whenever `rows` is populated.
    rowids: Optional[List[int]] = None

class ChartRequest(BaseModel):
    x_axis: str
    y_axis: str
    aggregation: str
    chart_type: str

# --- Canvas aggregation (Phase 5 / TASK-011) --------------------------------
class AggregateFilter(BaseModel):
    """One equality cross-filter (Canvas slicer): keep only rows where `column`
    equals `value`. `value=None` selects the NULL group (IS NULL). Applied as an
    Ibis-parameterized predicate -- the value travels as a typed literal, never
    interpolated into SQL (ADR-012)."""
    column: str
    value: Optional[Union[str, int, float, bool]] = None

class AggregateRequest(BaseModel):
    """One KPI or chart aggregation over a single session table.

    dimension=None  -> scalar KPI (one number, e.g. SUM(amount) or COUNT(*)).
    dimension set   -> grouped series (dimension x aggregated measure).
    measure=None    -> only valid for `count` (COUNT(*)).

    Typed params only: the SQL is Ibis-compiled from column names validated
    against the LIVE schema, so nothing here is interpolated into SQL (ADR-012).
    Single-table (ADR-006) -- the router resolves which table this targets."""
    dimension: Optional[str] = None
    # Optional SECOND grouping dimension -- the "breakdown"/series (TASK-025 / Wave 5).
    # When set (and `dimension` is also set), the result is 2-D: keys x series_keys ->
    # matrix, feeding stacked/grouped bars, multi-line and heatmaps. None => 1-D as before.
    series: Optional[str] = None
    measure: Optional[str] = None
    aggregation: Literal["sum", "avg", "count", "count_distinct", "min", "max"]
    limit: int = 50  # top-N categories for a grouped series; clamped server-side.
    # Cross-filter slicers (Canvas): AND-ed equality predicates applied BEFORE the
    # aggregation. Empty by default, so a KPI/series request without a slice is
    # unchanged. Column names are validated against the live schema server-side.
    filters: List[AggregateFilter] = Field(default_factory=list)
    # Scatter mode (Wave 5): when `measure_y` is set, the service returns RAW (x, y)
    # POINTS instead of a grouped aggregate -- a point cloud over two numeric measures.
    # `dimension`, if set, is the optional colour/group column (categorical). `aggregation`
    # is ignored in scatter mode. `top_points` caps the rows returned (server-clamped).
    measure_y: Optional[str] = None
    top_points: int = 1000
    # Box-plot mode (Wave 5): when true, group `measure` by `dimension` and return per-group
    # [min, Q1, median, Q3, max] stats (DuckDB quantile_cont). `measure` must be numeric and
    # `dimension` (the category) must be set; `aggregation`/`series`/`measure_y` are ignored.
    box: bool = False

class AggregateResponse(BaseModel):
    """Result of one aggregation. KPI: keys=[] and values=[<the number>]. Series:
    keys/values are parallel arrays (keys[i] -> values[i]). `values`/`keys` are
    `Any` because min/max over a date column yields an ISO date string and a
    dimension value can be str/int/date/null. `compiled_sql` mirrors the
    transparency of TransformPreviewResponse; `truncated` flags a capped series.

    2-D breakdown (TASK-025 / Wave 5): when the request set `series`, `series` names
    the breakdown column, `series_keys` are its top-M values, `matrix[i][j]` is the
    aggregate for keys[i] x series_keys[j] (None => no rows), and `values` is []. When
    `series` is None the 2-D fields default empty and the shape is unchanged (1-D)."""
    dimension: Optional[str] = None
    series: Optional[str] = None
    measure: Optional[str] = None
    aggregation: str
    keys: List[Any]
    values: List[Any]
    series_keys: List[Any] = Field(default_factory=list)
    matrix: List[List[Any]] = Field(default_factory=list)
    compiled_sql: str
    truncated: bool
    # Scatter mode (Wave 5): when the request set `measure_y`, this holds the raw points
    # as [{x, y, group?}] and keys/values/matrix are empty. None otherwise.
    points: Optional[List[Dict[str, Any]]] = None
    # Box-plot mode (Wave 5): when the request set `box`, this holds per-category stats as
    # [{key, min, q1, median, q3, max}] and keys/values/matrix are empty. None otherwise.
    boxes: Optional[List[Dict[str, Any]]] = None

# --- Column profiler (Table data-prep / TASK-015) ---------------------------
class ProfileHistogramBin(BaseModel):
    """One fixed-width numeric histogram bar. x0/x1 are server-computed float bin
    edges (from the column's own MIN/MAX); the last bin's x1 is the exact MAX."""
    x0: float
    x1: float
    count: int

class ProfileTopValue(BaseModel):
    """One most-frequent non-null value + its row count. `value` is `Any` because a
    category can be str/int/bool and a date value comes back as an ISO string."""
    value: Any
    count: int

class ColumnProfile(BaseModel):
    """Statistical profile of ONE column, computed server-side over the whole table
    via Ibis-compiled DuckDB SQL (never a client-side reduction of the grid window).
    Completeness fields are always present; the kind-specific fields are populated by
    `kind`: numeric -> mean/median/std + histogram; temporal -> min/max + top_values;
    categorical/boolean -> top_values. `min`/`max` are `Any` (ISO string for dates)."""
    column: str
    type: str  # raw DuckDB type as reported by PRAGMA table_info
    kind: Literal["numeric", "temporal", "categorical", "boolean"]
    total: int
    non_null: int
    null_count: int
    null_pct: float
    distinct: int
    min: Optional[Any] = None
    max: Optional[Any] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    std: Optional[float] = None
    histogram: List[ProfileHistogramBin] = Field(default_factory=list)
    top_values: List[ProfileTopValue] = Field(default_factory=list)
    compiled_sql: str

# --- Data-quality panel (Table data-prep / TASK-016) ------------------------
class ColumnValues(BaseModel):
    """TASK-042: the distinct non-null values of ONE column, most-frequent first, for the
    find/replace dropdown in the cleaning dialog. Bounded by a server cap; `truncated` is
    True when the column has MORE distinct values than were returned (the UI keeps
    free-text entry so a high-cardinality column is still editable). Read-only; Ibis-
    compiled from the column name validated against the live schema (ADR-012)."""
    column: str
    values: List[Any]
    distinct: int  # number of values returned (== distinct count unless `truncated`)
    truncated: bool

class QualityFinding(BaseModel):
    """One issue detected by a whole-table quality scan. `code` is the machine kind
    (drives grouping/tests); `column` is the offending column (None for table-level
    findings like duplicate rows). `suggested_op` is the OpKind the one-click "Fix"
    button opens in the existing cleaning dialog (None => informational, no button) --
    the fix routes through OpDialog's dry-run preview, so this scan never mutates data."""
    id: str  # stable key for the UI list + dedupe, e.g. "high_null:rep" or "duplicate_rows"
    code: Literal[
        "empty_column", "high_null", "duplicate_rows", "text_as_date",
        "text_as_number", "mixed_values", "whitespace", "constant",
        # TASK-021: hidden nulls, casing variants, mixed date formats, out-of-range values
        "hidden_null", "inconsistent_case", "mixed_date_format",
        "negative_values", "future_date",
        # TASK-041 #6/#8: sub-threshold nulls, and punctuation/spacing category variants
        "partial_null", "inconsistent_values",
    ]
    severity: Literal["high", "medium", "low", "info"]
    title: str
    detail: str
    column: Optional[str] = None
    metric: Optional[float] = None  # headline number (a % or a count) for display
    suggested_op: Optional[str] = None  # an OpKind value (see TransformParam), or None
    # TASK-041 #2: pre-filled fields for the one-click Fix, spread into the OpDialog
    # form so a fix like "cast to DATE, coerce" or "keep rows >= 0" is one tap. None
    # => the dialog opens with its own defaults (unchanged behaviour).
    suggested_params: Optional[Dict[str, Any]] = None
    # TASK-042: an OPTIONAL SECOND fix for the same finding. e.g. negative_values offers
    # both "keep >= 0" (suggested_op=filter_rows) and "make positive" here. None => the
    # finding has just the one fix. Same shape as suggested_op/params; the UI renders a
    # second Fix button and routes it through the same dry-run-previewed OpDialog.
    alt_op: Optional[str] = None
    alt_params: Optional[Dict[str, Any]] = None

class QualityReport(BaseModel):
    """Result of a whole-table quality scan, computed server-side over the full table
    via Ibis-compiled DuckDB SQL (<=4 queries regardless of width). `ok` is True when
    no findings survived; `findings` is sorted most-severe first."""
    row_count: int
    column_count: int
    ok: bool
    findings: List[QualityFinding] = Field(default_factory=list)
    compiled_sql: str

class AskTurn(BaseModel):
    """One prior (question -> SQL) turn, supplied by the client so a follow-up like
    "now group by month" can refine the previous query (#21 conversational
    refinement). Pure prompt context: the `sql` here is the app's OWN prior output
    that was already validated + dry-run clean; it is never executed or trusted as
    a query -- it only helps the model understand what "that" refers to."""
    question: str = Field(..., max_length=2000)
    sql: str = Field(..., max_length=50000)

class AskRequest(BaseModel):
    question: str = Field(..., max_length=2000)
    # #21: optional prior turns (oldest -> newest) so a follow-up refines the last
    # query instead of starting cold. Optional ⇒ the single-shot contract is intact.
    history: Optional[List[AskTurn]] = None

class AskResponse(BaseModel):
    sql: str = Field(..., max_length=50000)
    cache_hit: bool
    retries_used: int

class ExecuteRequest(BaseModel):
    sql: str = Field(..., max_length=50000)

class MaterializeRequest(BaseModel):
    """#23: persist a Query Engine SELECT's result as a real, reusable session table.
    `sql` is the reviewed SELECT (re-validated + tenant-scoped server-side, exactly
    like /execute); `name` is an optional friendly table name (sanitized + deduped
    server-side, defaulting to 'query_result')."""
    sql: str = Field(..., max_length=50000)
    name: Optional[str] = None

class ExecuteResponse(BaseModel):
    query_id: str
    status: Literal["running", "completed", "failed", "cancelled"]

class QueryPollResponse(BaseModel):
    status: Literal["running", "completed", "failed", "cancelled"]
    result: Optional[bytes] = None  # MessagePack ref
    error: Optional[str] = None

class ExecuteResultResponse(BaseModel):
    """Synchronous /execute result (Phase 6). Rows come back as JSON, mirroring
    DataResponse -- a query result stays debuggable, matching the "small results
    stay JSON" choice already made for /data and /aggregate. The documented async
    query_id/poll/MessagePack path (ExecuteResponse + QueryPollResponse, kept above)
    is deferred. `columns` reuses PreviewColumn {name,type}; `truncated` flags a
    result trimmed at the server row cap."""
    columns: List[PreviewColumn]
    rows: List[Dict[str, Any]]
    row_count: int
    truncated: bool

class ExportRowsRequest(BaseModel):
    """Payload for POST /export/rows (#24, Wave 2): query-result rows the client
    already holds, encoded server-side to .xlsx. `columns` fixes the output column
    order; `rows` are dicts keyed by column name (as returned by /execute). Server
    export is xlsx only -- CSV/JSON/clipboard are built client-side from these rows."""
    columns: List[str]
    rows: List[Dict[str, Any]]
    format: Literal["xlsx"] = "xlsx"

class CustomInstruction(BaseModel):
    term: str
    definition: str

# --- Wave 4: AI batch (Foundation 2 — one LiteLLM route pattern, 6 features) ---
# Every model below is "prompt-context in / typed-result out". NO SQL is assembled
# from any of these fields. The two SQL-PRODUCING modes (fix, optimize) return SQL
# that is re-validated + sandbox-dry-run exactly like /ask before it reaches the
# client (ADR-010, ADR-013); the client still never auto-runs it (the Review Gate).

class SqlAssistRequest(BaseModel):
    """#22: act on the SQL the user has in the editor. `mode=fix` uses the DuckDB
    error text (from a failed /execute); explain/optimize ignore it. `sql` is the
    editor's current text -- it is treated as untrusted and re-validated server-side."""
    mode: Literal["explain", "fix", "optimize"]
    sql: str = Field(..., max_length=50000)
    error: Optional[str] = None

class SqlAssistResponse(BaseModel):
    """`fix`/`optimize` return a NEW `sql` (validated + dry-run clean, for the Review
    Gate -- never auto-run); `explain` returns `sql=None`. `explanation` is always the
    human-readable prose. `retries_used` mirrors AskResponse (0 for explain)."""
    mode: str
    sql: Optional[str] = None
    explanation: str
    retries_used: int = 0

class SuggestQuestionsResponse(BaseModel):
    """#26 auto-EDA: analytical questions answerable from the loaded schema, each
    ready to drop straight into /ask. Cached per schema_version."""
    questions: List[str]
    cache_hit: bool = False

class NarrativeResponse(BaseModel):
    """#29 data storytelling and #18 explain-chart: a plain-prose narrative. `cache_hit`
    is meaningful only for the schema-keyed dataset story; explain-chart leaves it False."""
    narrative: str
    cache_hit: bool = False

class RecommendChartRequest(BaseModel):
    """#30: recommend a chart type for one column. `column`/`column_type` come from the
    client's live schema and are used ONLY as prompt text (no SQL is built from them).
    `intent` is an optional free-text hint ("show the trend over time")."""
    column: str
    column_type: Optional[str] = None
    intent: Optional[str] = None

class RecommendChartResponse(BaseModel):
    """A recommended chart type from the Canvas-supported set + why, plus up to two
    alternatives. `chart_type` is advisory text the UI maps onto its own picker."""
    chart_type: str
    reasoning: str
    alternatives: List[str] = Field(default_factory=list)

class ExplainChartRequest(BaseModel):
    """#18: narrate one Canvas chart. Mirrors the AggregateResponse the tile already
    holds (aggregation + parallel keys/values) plus its chart_type / dimension / measure.
    No new query runs -- this is the data the client already has, sent back as context."""
    title: Optional[str] = None
    chart_type: str
    dimension: Optional[str] = None
    measure: Optional[str] = None
    aggregation: str
    keys: List[Any] = Field(default_factory=list)
    values: List[Any] = Field(default_factory=list)

class ScheduleRequest(BaseModel):
    question: str = Field(..., max_length=2000)
    cron: str

class ScheduleResponse(BaseModel):
    schedule_id: str
    next_run: str

class ErrorResponse(BaseModel):
    error: str
    message: str
    retryable: bool


# --- Dashboards ---

class DashboardCreate(BaseModel):
    session_uuid: str
    name: str = Field(..., max_length=255)
    pages_json: str

class DashboardUpdate(BaseModel):
    name: Optional[str] = None
    pages_json: Optional[str] = None

class DashboardResponse(BaseModel):
    id: int
    session_uuid: str
    name: str = Field(..., max_length=255)
    pages_json: str
    created_at: datetime
    updated_at: datetime


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., max_length=255)

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
