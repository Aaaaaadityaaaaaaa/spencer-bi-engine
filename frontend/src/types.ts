// Shared types for the frontend <-> backend contract (Phase 4 / TASK-006).
// Field names are snake_case to match the FastAPI JSON payloads verbatim, so no
// key remapping is needed at the call sites.

export interface ColumnMeta {
  name: string
  type: string
  cardinality?: number
}

// POST /sessions response (SessionResponse in backend/models/schemas.py).
export interface SessionInfo {
  session_uuid: string
  table_name: string
  row_count: number
  columns: ColumnMeta[]
}

// --- Auth & multi-tenancy (TASK-027) ---
// Mirrors backend UserResponse / TokenResponse. `created_at` is an ISO string.
export interface AuthUser {
  id: number
  email: string
  is_admin: boolean
  created_at: string
}

// POST /auth/register and /auth/login both return this (TokenResponse).
export interface AuthTokenResponse {
  access_token: string
  token_type: string
  user: AuthUser
}

// A column descriptor inside DataResponse (backend PreviewColumn: name + type).
export interface DataColumn {
  name: string
  type: string
}

// GET /sessions/{id}/data response (DataResponse in backend/models/schemas.py).
export interface DataResponse {
  columns: DataColumn[]
  rows: Record<string, unknown>[]
  total: number
  offset: number
  limit: number
  // TASK-022: whole-table [min, max] per numeric column, for the grid's heatmap
  // colour scale. Present only on the first window (offset 0); the grid caches it.
  ranges?: Record<string, [number, number]>
}

// --- In-grid view controls (TASK-022) ---
// Sort travels to /data as "col:dir,col2:dir2"; the grid owns the spec and its order.
export type SortDir = 'asc' | 'desc'
export interface SortSpec {
  column: string
  dir: SortDir
}

// --- Cleaning / transform contract (TASK-010) ---
// Mirrors the backend TransformParam discriminated union (backend/models/schemas.py).
// snake_case field names match the JSON bodies verbatim.

export type ImputeStrategy = 'zero' | 'mean' | 'median' | 'mode' | 'custom'
export type DedupeKeep = 'first' | 'last'
export type StringCase = 'upper' | 'lower' | 'capitalize'
export type FilterAction = 'keep' | 'remove'
// --- TASK-018 derive-op literal unions ---
export type SplitMode = 'delimiter' | 'regex'
export type DateExtractMode = 'part' | 'format'
export type DatePart =
  | 'year'
  | 'month'
  | 'day'
  | 'quarter'
  | 'dayofyear'
  | 'weekday'
  | 'weekday_name'
  | 'hour'
  | 'minute'
  | 'second'
export type BinMethod = 'equal_width' | 'quantile'
export type PadSide = 'left' | 'right'
// --- TASK-019 (Wave 1b) ordered-window ops ---
export type FillDirection = 'down' | 'up'
export type OutlierMethod = 'zscore'

export interface DedupeOp {
  op: 'dedupe'
}
export interface DropNullOp {
  op: 'drop_null'
  column: string
}
export interface ImputeNullOp {
  op: 'impute_null'
  column: string
  strategy: ImputeStrategy
  fill_value?: unknown
}
export interface CastOp {
  op: 'cast'
  column: string
  new_type: string
  // When true, un-parseable values become NULL (TRY_CAST) rather than failing the
  // whole cast (TASK-017). Optional; omitted/false == strict CAST.
  coerce?: boolean
}
export interface CalculatedColumnOp {
  op: 'calculated_column'
  new_column_name: string
  formula: string
}
export interface DropColumnOp {
  op: 'drop_column'
  column: string
}
export interface RenameColumnOp {
  op: 'rename_column'
  column: string
  new_name: string
}
export interface DedupeSubsetOp {
  op: 'dedupe_subset'
  columns: string[]
  keep: DedupeKeep
}
export interface StringNormalizeOp {
  op: 'string_normalize'
  column: string
  trim?: boolean
  case?: StringCase
  find?: string
  replace?: string
  null_token?: string
  // --- TASK-018 text-toolkit extensions (all optional ⇒ backward-compatible) ---
  // `regex: true` makes `find` a regex (REGEXP_REPLACE, global) instead of a literal
  // replace. `strip_special` removes every non-alphanumeric char (spaces kept).
  // `pad_*` left/right-pads to `pad_length` with a single `pad_char`.
  regex?: boolean
  strip_special?: boolean
  pad_side?: PadSide
  pad_length?: number
  pad_char?: string
}
// --- TASK-018 derive ops (add a new column from one source column) ---
export interface SplitColumnOp {
  op: 'split_column'
  column: string
  new_column_name: string
  mode: SplitMode
  delimiter?: string
  index?: number
  pattern?: string
  group?: number
}
export interface DateExtractOp {
  op: 'date_extract'
  column: string
  new_column_name: string
  mode: DateExtractMode
  part?: DatePart
  date_format?: string
}
export interface BinColumnOp {
  op: 'bin_column'
  column: string
  new_column_name: string
  method: BinMethod
  bins: number
}
export interface FilterRowsOp {
  op: 'filter_rows'
  predicate: string
  action: FilterAction
}
// --- TASK-019 (Wave 1b) ---
export interface FillDownOp {
  op: 'fill_down'
  column: string
  direction: FillDirection
}
export interface FlagOutliersOp {
  op: 'flag_outliers'
  column: string
  new_column_name: string
  method: OutlierMethod
  threshold: number
}

export type TransformOp =
  | DedupeOp
  | DropNullOp
  | ImputeNullOp
  | CastOp
  | CalculatedColumnOp
  | DropColumnOp
  | RenameColumnOp
  | DedupeSubsetOp
  | StringNormalizeOp
  | SplitColumnOp
  | DateExtractOp
  | BinColumnOp
  | FillDownOp
  | FlagOutliersOp
  | FilterRowsOp

// The discriminator value alone (e.g. 'drop_null'), handy for menus + dispatch.
export type OpKind = TransformOp['op']

// A request to open the cleaning dialog for a given op, optionally pre-scoped to a
// column (the per-column ⋮ header menu sets `column`; ribbon buttons leave it unset
// so the dialog shows a column picker). A Fix from the quality panel may also
// pre-seed cast specifics (`coerce`, `newType`) so it's genuinely one click (TASK-017).
export interface OpRequest {
  op: OpKind
  column?: string
  coerce?: boolean
  newType?: string
}

// apply / undo / redo all return this (TransformResponse in the backend).
export interface TransformResponse {
  schema_version: number
  step: number
  row_count: number
}

// POST /transform/preview response (TransformPreviewResponse) — a dry run that
// neither materializes nor bumps the version, safe to call on every param change.
export interface TransformPreviewResponse {
  op: string
  row_count_before: number
  row_count_after: number
  row_count_delta: number
  columns: DataColumn[]
  sample: Record<string, unknown>[]
  compiled_sql: string
  // Only present for a coercing cast: how many non-null values would be nulled
  // because they can't parse into the target type (TASK-017).
  coerced_null_count?: number
}

// GET /history response (HistoryResponse) — drives undo/redo button enablement.
export interface HistoryStep {
  step: number
  op: string
  column: string | null
  timestamp: string
}
export interface HistoryResponse {
  steps: HistoryStep[]
  current_step_index: number
  total_steps: number
  can_undo: boolean
  can_redo: boolean
}

// GET /schema response (SchemaResponse) — re-read after a transform to resync columns.
export interface SchemaTable {
  table_name: string
  is_primary: boolean
  columns: ColumnMeta[]
}
export interface SchemaResponse {
  tables: SchemaTable[]
}

// --- Canvas aggregation contract (Phase 5 / TASK-011) ---
// Mirrors AggregateRequest / AggregateResponse in backend/models/schemas.py.
// One shape serves both KPI cards (dimension omitted → a single scalar) and chart
// tiles (dimension set → a grouped series).

export type Aggregation = 'sum' | 'avg' | 'count' | 'count_distinct' | 'min' | 'max'

/** A dimension value: text/number/bool label, or null for the NULL group. */
export type AggregateKey = string | number | boolean | null
/** An aggregated value: a number, an ISO string (MIN/MAX over a date), or null. */
export type AggregateValue = number | string | null

/** One equality cross-filter (Canvas slicer): keep rows where `column` = `value`.
 *  `value: null` selects the NULL group (IS NULL). Mirrors backend AggregateFilter. */
export interface AggregateFilter {
  column: string
  value: AggregateKey
}

// POST /sessions/{id}/aggregate body. `measure` may only be omitted for `count`
// (⇒ COUNT(*)); the backend enforces this and returns 400 otherwise. `filters` are
// AND-ed equality slicers (cross-filter); omitted from the body when no slice is active.
export interface AggregateRequest {
  dimension?: string | null
  // Optional SECOND grouping dimension — the "breakdown"/series (TASK-025 / Wave 5).
  // Set alongside `dimension` for a 2-D result (keys × series_keys → matrix); omitted
  // ⇒ the 1-D KPI/series shape is unchanged.
  series?: string | null
  measure?: string | null
  aggregation: Aggregation
  limit?: number
  filters?: AggregateFilter[]
}

// POST /sessions/{id}/aggregate response. For a KPI, `keys` is empty and the number
// is `values[0]`. For a series, `keys[i]` pairs with `values[i]`. For a 2-D breakdown
// (request set `series`), `series_keys` are the breakdown values and `matrix[i][j]` is
// the aggregate for keys[i] × series_keys[j] (null ⇒ no rows); `values` is then empty.
export interface AggregateResponse {
  dimension: string | null
  series?: string | null
  measure: string | null
  aggregation: Aggregation
  keys: AggregateKey[]
  values: AggregateValue[]
  series_keys?: AggregateKey[]
  matrix?: AggregateValue[][]
  compiled_sql: string
  truncated: boolean
}

// --- Canvas tile configuration (frontend-only view state) ---
// Not a wire contract, so these use camelCase: `chartType` never leaves the browser
// (the backend aggregates; it does not care how the result is drawn).

export type ChartType = 'bar' | 'line' | 'area' | 'hbar' | 'pie' | 'stacked' | 'heatmap' | 'treemap' | 'funnel'

/** Chart types that read the optional `series` breakdown (2-D dimension × series).
 *  The others ignore it — ChartCanvas drops `series` from the request for them, and the
 *  Breakdown picker is hidden — so a stale breakdown can never corrupt a 1-D shape. */
const BREAKDOWN_CHART_TYPES: ReadonlySet<ChartType> = new Set(['bar', 'line', 'area', 'stacked', 'heatmap'])
export function supportsBreakdown(t: ChartType): boolean {
  return BREAKDOWN_CHART_TYPES.has(t)
}

export interface KpiConfig {
  id: number
  measure: string | null // null ⇒ COUNT(*) ("Total rows")
  aggregation: Aggregation
  // TASK-026 (#14): optional target threshold. When set and the value is numeric, the
  // card shows a ▲/▼ delta vs the target; `targetMode` decides which direction is "good"
  // (green). Both optional ⇒ existing cards / saved dashboards are unaffected.
  target?: number | null
  targetMode?: KpiTargetMode
}

/** Whether meeting-or-beating the target is good (revenue) or bad (cost/error rate). */
export type KpiTargetMode = 'higher_better' | 'lower_better'

export interface ChartConfig {
  dimension: string | null
  // Optional breakdown/series column (TASK-025). null ⇒ single-series (1-D). Only the
  // breakdown-capable chart types (bar/line/area/stacked/heatmap) read it.
  series: string | null
  measure: string | null
  aggregation: Aggregation
  chartType: ChartType
}

/** Per-tile fetch state, owned by ChartCanvas and passed down to the tiles. */
export interface TileState<T> {
  loading: boolean
  error: string | null
  data: T | null
}

// --- Dashboard persistence + templates (TASK-026 / Wave 6) ---
// A dashboard reduces to its tile CONFIGS (KPI + chart specs) — no fetch state, no data.
// That snapshot is what a template produces, what "Save" stores, and what "Load" restores;
// ChartCanvas re-runs every aggregation from it. Persisted client-side in localStorage
// (single-user app), mirroring the saved-queries store.
export interface DashboardSnapshot {
  kpis: KpiConfig[]
  charts: ChartConfig[]
}
export interface SavedDashboard extends DashboardSnapshot {
  id: string
  name: string
  savedAt: string // ISO timestamp
}

// --- Query Engine contract (Phase 6 / TASK-012) ---
// Mirrors AskRequest/AskResponse, ExecuteRequest/ExecuteResultResponse and
// CustomInstruction in backend/models/schemas.py. snake_case matches the wire.

// POST /sessions/{id}/ask response. `sql` is dropped into the editor (the Review
// Gate) for the user to inspect/run -- it is never auto-executed. `cache_hit` flags
// a version-keyed cache hit; `retries_used` is how many self-correction passes the
// model needed before the SQL validated + dry-ran clean (0 => first attempt worked).
export interface AskResponse {
  sql: string
  cache_hit: boolean
  retries_used: number
}

// --- Wave 4: AI batch (#21 refine, #22 assist, #26 EDA, #29 story, #30 recommend, #18 explain) ---
// Every shape below mirrors a backend model in schemas.py; snake_case matches the wire.

/** #21 conversational refinement: one prior (question -> SQL) turn the client replays so
 *  a follow-up ("now group by month") refines the last query. `sql` is the app's OWN
 *  prior validated output — pure prompt context, never re-executed or trusted server-side. */
export interface AskTurn {
  question: string
  sql: string
}

/** #22: which action the SQL-assist endpoint performs on the editor's current SQL. */
export type SqlAssistMode = 'explain' | 'fix' | 'optimize'

// POST /sessions/{id}/sql/assist response. `explain` returns prose only (sql=null);
// `fix`/`optimize` return a NEW validated SELECT for the Review Gate (never auto-run).
export interface SqlAssistResponse {
  mode: SqlAssistMode
  sql: string | null
  explanation: string
  retries_used: number
}

// GET /sessions/{id}/suggest-questions response (#26 auto-EDA).
export interface SuggestQuestionsResponse {
  questions: string[]
  cache_hit: boolean
}

// #29 data storytelling and #18 explain-chart both return this prose blob.
export interface NarrativeResponse {
  narrative: string
  cache_hit: boolean
}

// POST /sessions/{id}/recommend-chart response (#30). `chart_type` is advisory text the
// UI maps onto its own ChartType picker; `alternatives` are up to two runners-up.
export interface RecommendChartResponse {
  chart_type: string
  reasoning: string
  alternatives: string[]
}

// POST /sessions/{id}/explain-chart body (#18). Mirrors ExplainChartRequest: the client
// already holds all of this from the tile's aggregate, so no new query runs server-side.
export interface ExplainChartRequest {
  title?: string | null
  chart_type: string
  dimension?: string | null
  measure?: string | null
  aggregation: string
  keys: AggregateKey[]
  values: AggregateValue[]
}

// POST /sessions/{id}/execute response (ExecuteResultResponse). One-shot, in-memory
// rows (not windowed like /data): the sandboxed query returns the whole capped result
// at once. `truncated` is true when the result hit the server row cap. `columns`
// reuses DataColumn {name,type}.
export interface ExecuteResultResponse {
  columns: DataColumn[]
  rows: Record<string, unknown>[]
  row_count: number
  truncated: boolean
}

// One business-dictionary entry (CustomInstruction). Feeds the NL->SQL prompt; an
// add/delete bumps bizdict_version server-side, invalidating stale cached SQL.
export interface CustomInstruction {
  term: string
  definition: string
}

// --- Column profiler contract (Table data-prep / TASK-015) ---
// Mirrors ColumnProfile / ProfileHistogramBin / ProfileTopValue in
// backend/models/schemas.py. snake_case matches the wire. All numbers are computed
// server-side over the whole table (not a reduction of the grid window).

export type ColumnProfileKind = 'numeric' | 'temporal' | 'categorical' | 'boolean'

/** One fixed-width numeric histogram bar; x0/x1 are server-computed bin edges. */
export interface ProfileHistogramBin {
  x0: number
  x1: number
  count: number
}

/** One most-frequent non-null value + its row count. */
export interface ProfileTopValue {
  value: string | number | boolean | null
  count: number
}

// GET /sessions/{id}/profile/column response. Completeness fields are always set;
// the kind-specific fields populate by `kind` (numeric ⇒ mean/median/std + histogram;
// temporal ⇒ min/max + top_values; categorical/boolean ⇒ top_values). `min`/`max`
// are number | string (ISO date) | null.
export interface ColumnProfile {
  column: string
  type: string
  kind: ColumnProfileKind
  total: number
  non_null: number
  null_count: number
  null_pct: number
  distinct: number
  min: number | string | null
  max: number | string | null
  mean: number | null
  median: number | null
  std: number | null
  histogram: ProfileHistogramBin[]
  top_values: ProfileTopValue[]
  compiled_sql: string
}

// --- Data-quality panel contract (Table data-prep / TASK-016) ---
// Mirrors QualityReport / QualityFinding in backend/models/schemas.py. snake_case
// matches the wire. Every number is computed server-side over the WHOLE table.

export type QualitySeverity = 'high' | 'medium' | 'low' | 'info'

export type QualityCode =
  | 'empty_column'
  | 'high_null'
  | 'duplicate_rows'
  | 'text_as_date'
  | 'text_as_number'
  | 'mixed_values'
  | 'whitespace'
  | 'constant'
  // TASK-021: hidden nulls, casing variants, mixed date formats, out-of-range values
  | 'hidden_null'
  | 'inconsistent_case'
  | 'mixed_date_format'
  | 'negative_values'
  | 'future_date'

/** One detected issue. `column` is null for table-level findings (duplicate rows).
 *  `suggested_op` is the OpKind the one-click Fix opens in OpDialog (null ⇒ no Fix,
 *  informational only); `metric` is the headline number (a % or a count). */
export interface QualityFinding {
  id: string
  code: QualityCode
  severity: QualitySeverity
  title: string
  detail: string
  column: string | null
  metric: number | null
  suggested_op: OpKind | null
}

// GET /sessions/{id}/quality response. `ok` is true when no findings survived;
// `findings` is sorted most-severe first.
export interface QualityReport {
  row_count: number
  column_count: number
  ok: boolean
  findings: QualityFinding[]
  compiled_sql: string
}
