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
  // TASK-041 #5: the DuckDB rowid for each row in `rows` (parallel array), so the grid
  // can address an exact cell for in-cell editing. Present on every window.
  rowids?: number[]
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
  // TASK-041 #4: round a computed mean/median fill to this many decimal places
  // (ignored for zero/mode/custom). Omitted ⇒ no rounding (raw mean/median).
  decimals?: number
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
  // TASK-041 #3/#6: collapse internal runs of whitespace to a single space and trim
  // the ends — merges spacing variants ("u . p . i" vs "u.p.i"). Runs after strip_special.
  collapse_whitespace?: boolean
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
// TASK-041 #5: in-cell edit — set ONE cell (identified by its stable DuckDB rowid) to a
// new value. `value` omitted/undefined clears to NULL; otherwise the backend CASTs the
// string to the column's type in compiled SQL (a value that can't parse fails as a 400).
export interface UpdateCellOp {
  op: 'update_cell'
  column: string
  rowid: number
  value?: unknown
}

// TASK-042: replace a numeric column with its absolute value IN PLACE (drop the negative
// sign) — the "make positive" alternative to dropping rows on the negative-values finding.
export interface AbsoluteValueOp {
  op: 'absolute_value'
  column: string
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
  | UpdateCellOp
  | AbsoluteValueOp

// The discriminator value alone (e.g. 'drop_null'), handy for menus + dispatch.
export type OpKind = TransformOp['op']

// A request to open the cleaning dialog for a given op, optionally pre-scoped to a
// column (the per-column ⋮ header menu sets `column`; ribbon buttons leave it unset
// so the dialog shows a column picker). A Fix from the quality panel may also
// pre-seed cast specifics (`coerce`, `newType`) so it's genuinely one click (TASK-017).
// `seed` (TASK-041 #2/#3/#6) carries a finding's `suggested_params` verbatim — snake_case
// op-field keys the dialog maps onto its form so newer fixes open ready to apply.
export interface OpRequest {
  op: OpKind
  column?: string
  coerce?: boolean
  newType?: string
  seed?: Record<string, unknown>
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

// POST /sessions/{id}/tables response (TableUploadResponse) — a secondary table added
// to an existing session (registered with is_primary=false server-side). Mirrors
// backend TableUploadResponse; the switcher then lists it alongside the primary.
export interface TableUploadResponse {
  table_name: string
  row_count: number
  columns: ColumnMeta[]
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
  // Wave 5 scatter: when set, the backend returns raw (x, y) points instead of a grouped
  // aggregate. `measure` is the X axis, `measure_y` the Y axis; optional `dimension` colours
  // the points. `aggregation` is ignored in scatter mode.
  measure_y?: string | null
  top_points?: number
  // Wave 5 box plot: when true, group `measure` by `dimension` and return per-category
  // [min, Q1, median, Q3, max] stats. `dimension` (category) must be set. Optional ⇒ back-compat.
  box?: boolean
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
  // Scatter mode (Wave 5): raw points when the request set `measure_y`; null otherwise.
  points?: Array<{ x: AggregateValue; y: AggregateValue; group?: AggregateKey }> | null
  // Box-plot mode (Wave 5): per-category stats when the request set `box`; null otherwise.
  boxes?: Array<{ key: AggregateKey; min: AggregateValue; q1: AggregateValue; median: AggregateValue; q3: AggregateValue; max: AggregateValue; n?: number }> | null
}

// --- Canvas tile configuration (frontend-only view state) ---
// Not a wire contract, so these use camelCase: `chartType` never leaves the browser
// (the backend aggregates; it does not care how the result is drawn).

export type ChartType = 'bar' | 'line' | 'area' | 'hbar' | 'pie' | 'stacked' | 'heatmap' | 'treemap' | 'funnel' | 'scatter' | 'box' | 'gauge' | 'slicer'

/** Chart types that read the optional `series` breakdown (2-D dimension × series).
 *  The others ignore it — ChartCanvas drops `series` from the request for them, and the
 *  Breakdown picker is hidden — so a stale breakdown can never corrupt a 1-D shape. */
const BREAKDOWN_CHART_TYPES: ReadonlySet<ChartType> = new Set(['bar', 'line', 'area', 'stacked', 'heatmap'])
export function supportsBreakdown(t: ChartType): boolean {
  return BREAKDOWN_CHART_TYPES.has(t)
}

/** Scatter uses two measures (X = `measure`, Y = `measureY`) and an optional colour
 *  column (`dimension`). It is NOT a breakdown type. */
export function supportsMeasureY(t: ChartType): boolean {
  return t === 'scatter'
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
  // TASK-031 (#14 part 2): optional temporal column to plot the metric over time as a
  // sparkline. Frontend-only (never sent to the backend); the trend is the existing
  // /aggregate with `dimension` set to this column. Optional ⇒ back-compatible.
  trendDimension?: string | null
  // TASK-033 (Power BI Canvas): per-tile presentation overrides, all frontend-only and
  // all optional ⇒ existing cards / saved dashboards are unaffected.
  title?: string | null // overrides the auto "Sum of revenue"; null/blank ⇒ auto
  accent?: string | null // sparkline accent colour (hex/oklch); null ⇒ brand primary
  hideControls?: boolean // "clean" mode: hide the editor affordances, keep title+value+spark
  // TASK-036 (Power BI Canvas, part 4): more per-tile presentation, all optional/back-compat.
  bg?: string | null // card background fill (hex/oklch); null/absent ⇒ default surface
  bold?: boolean // bold the title AND the big value
  // Power BI–style drawer options (all optional / back-compatible).
  decimals?: number | null // per-KPI decimal places (null ⇒ global setting)
  thousands?: boolean | null // per-KPI thousands separator (null ⇒ global setting)
  currency?: boolean | null // per-KPI currency formatting (null ⇒ global setting)
  prefix?: string | null // text before the value, e.g. "$"
  suffix?: string | null // text after the value, e.g. "%", " kg"
  colorByTarget?: boolean // colour the value by target direction (default false)
  showSpark?: boolean // show the sparkline (default true)
  sparkType?: 'line' | 'area' | 'bar' // sparkline style (default 'line')
  align?: 'left' | 'center' // value alignment (default 'left')
  border?: boolean // card border (default true)
  radius?: 'sm' | 'md' | 'lg' // card corner radius (default 'md')
  shadow?: boolean // card drop shadow (default false)
  fontFamily?: string | null // custom font family
  valueFontSize?: number | null // custom font size for values
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
  // Wave 5 scatter: optional Y measure. Only used when chartType === 'scatter'; ignored
  // (and never sent to the backend) for every other type. Optional ⇒ back-compatible.
  measureY?: string | null
  chartType: ChartType
  // TASK-033 (Power BI Canvas): per-tile presentation overrides, all frontend-only and
  // all optional ⇒ existing tiles / saved dashboards render exactly as before.
  title?: string | null // overrides the auto "Sum of revenue by region"; null/blank ⇒ auto
  color?: string | null // single-series accent (hex/oklch); a breakdown keeps the categorical palette
  showValues?: boolean // draw value/count data labels on the plot
  hideControls?: boolean // "clean" mode: hide the control strip, keep the title + plot
  // TASK-036 (Power BI Canvas, part 4): more per-tile presentation, all optional/back-compat.
  bg?: string | null // card background fill (hex/oklch); null/absent ⇒ default surface
  bold?: boolean // bold the title
  topN?: number | null // cap grouped categories to the top-N by measure; null/absent ⇒ server default (top-50, value DESC)
  // Power BI–style drawer options (all optional / back-compatible).
  showLegend?: boolean // show the series legend on breakdown charts (default true)
  xTitle?: string | null // custom category/x-axis title (overrides the field name)
  yTitle?: string | null // custom value/y-axis title
  showGrid?: boolean // draw gridlines (default true)
  palette?: string | null // categorical palette id (see utils/chartPalette); null ⇒ default
  stacked100?: boolean // 100% stacked for bar/area/stacked
  referenceValue?: number | null // horizontal reference line on the value axis; null ⇒ none
  yScale?: 'linear' | 'log' // value-axis scale (default 'linear')
  smooth?: boolean // smooth line/area curves (default true)
  showMarkers?: boolean // point markers on line/area (default true)
  areaOpacity?: number | null // area fill opacity 0..1 (default 0.2)
  sortDir?: 'auto' | 'desc' | 'asc' | 'alpha' // category sort order (default 'auto' = top-N desc)
  border?: boolean // card border (default true)
  radius?: 'sm' | 'md' | 'lg' // card corner radius (default 'md')
  shadow?: boolean // card drop shadow (default false)
  fontFamily?: string | null // custom font family
  valueFontSize?: number | null // custom font size for values
}

/** Per-tile fetch state, owned by ChartCanvas and passed down to the tiles. */
export interface TileState<T> {
  loading: boolean
  error: string | null
  data: T | null
}

// --- Canvas grid + pages (TASK-034, Power BI Canvas) ---
// A chart tile keeps its numeric id alongside its config (the id lives on the wrapper so
// tiles can be added/removed and their fetch state keyed independently). This is the shape
// ChartCanvas works with in memory AND the shape persisted per-page below.
export interface PersistedChartEntry {
  id: number
  config: ChartConfig
}

// One tile's position + size on the freeform grid. `i` is the COMPOSITE tile id
// ("kpi:<id>" / "chart:<id>") — see utils/dashboardLayout. x/y/w/h are grid units
// (GRID_COLS-wide columns; h/w in row-height steps), exactly what grid-layout-plus stores.
export interface TileLayout {
  i: string
  x: number
  y: number
  w: number
  h: number
}

// One Canvas page: a named set of tiles + their grid layout. KPIs and charts share the one
// `layout` (a unified drag/resize surface). A dashboard is an ordered list of these pages.
export interface DashboardPage {
  id: string
  name: string
  kpis: KpiConfig[]
  charts: PersistedChartEntry[]
  layout: TileLayout[]
}

// --- Dashboard persistence + templates (TASK-026 / Wave 6, multi-page since TASK-034) ---
// A dashboard reduces to its PAGES (each a set of tile configs + their layout) — no fetch
// state, no data. That snapshot is what a template produces, what "Save" stores, and what
// "Load" restores; ChartCanvas re-runs every aggregation from it. Persisted client-side in
// localStorage (single-user app), mirroring the saved-queries store. `activePageId` records
// which page was in front when saved, so a load restores the same view.
export interface DashboardSnapshot {
  pages: DashboardPage[]
  activePageId: string
}
export interface SavedDashboard extends DashboardSnapshot {
  id: string
  name: string
  savedAt: string // ISO timestamp
}

// --- Live board auto-persistence (TASK-033 "persist immediately"; multi-page since TASK-034) ---
// Distinct from SavedDashboard (a named, explicit save): this is the ONE live board the
// user is actively working on, snapshotted to localStorage on every edit so a reload
// restores it. Keyed per user; tied to the dataset `sessionUuid` so a different dataset
// seeds fresh rather than showing a stale board.
//
// v1 (TASK-033) was single-page: `{ snapshot: { kpis, charts } }`, no layout. v2 (TASK-034)
// is multi-page with per-page layout. useActiveDashboard reads either and UPGRADES a v1 blob
// on read — wrapping its single {kpis,charts} into one "Page 1" with a generated flow layout
// — so a board saved before the grid upgrade survives it. The v1 types are retained purely
// for that upgrade path.
export interface ActiveDashboardSnapshot {
  kpis: KpiConfig[]
  charts: PersistedChartEntry[]
}
export interface ActiveDashboardBlobV1 {
  v: 1
  sessionUuid: string
  snapshot: ActiveDashboardSnapshot
}
export interface ActiveDashboardBlobV2 {
  v: 2
  sessionUuid: string
  pages: DashboardPage[]
  activePageId: string
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

// GET /sessions/{id}/column/values — distinct values of one column, most-frequent first,
// for the find/replace dropdown in the cleaning dialog (TASK-042). `truncated` ⇒ the
// column has more distinct values than returned (the UI keeps free-text entry).
export interface ColumnValues {
  column: string
  values: (string | number | boolean | null)[]
  distinct: number
  truncated: boolean
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
  // TASK-041: sub-threshold missingness (survives a cast, #8) + punctuation/spacing
  // variants of the same category ('u.p.i' vs 'upi', #3/#6)
  | 'partial_null'
  | 'inconsistent_values'

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
  // TASK-041 #2/#3/#6: pre-filled op params for the one-click Fix, passed through to the
  // OpDialog form as an OpRequest `seed` (snake_case op-field keys). Absent ⇒ the Fix
  // opens with only the op + column pre-scoped.
  suggested_params?: Record<string, unknown>
  // TASK-042: an OPTIONAL second fix for the same finding (e.g. negative_values also
  // offers "make positive" → absolute_value). Absent ⇒ only the primary Fix is shown.
  alt_op?: OpKind | null
  alt_params?: Record<string, unknown>
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
