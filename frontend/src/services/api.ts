// Single Axios client for the backend. Absolute baseURL (not a Vite proxy) so
// the browser talks to the API host directly; the backend CORS config already
// allows the :5173 dev origin. Override with VITE_API_BASE at build/dev time.
import axios from 'axios'
import type { AxiosError } from 'axios'
import type {
  SessionInfo,
  DataResponse,
  SortSpec,
  TransformOp,
  TransformResponse,
  TransformPreviewResponse,
  HistoryResponse,
  SchemaResponse,
  TableUploadResponse,
  AggregateRequest,
  AggregateResponse,
  ColumnProfile,
  QualityReport,
  AskResponse,
  AskTurn,
  SqlAssistMode,
  SqlAssistResponse,
  SuggestQuestionsResponse,
  NarrativeResponse,
  RecommendChartResponse,
  ExplainChartRequest,
  ExecuteResultResponse,
  CustomInstruction,
  AuthTokenResponse,
  AuthUser,
} from '../types'

const baseURL = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

const http = axios.create({ baseURL })

// --- Auth wiring (TASK-027) ---------------------------------------------------
// The bearer token lives here as the single source of truth for outgoing requests;
// useAuth keeps it in sync (setAuthToken on login/restore/logout). A request
// interceptor attaches it so no call site has to thread the header through.
let authToken: string | null = null
export function setAuthToken(token: string | null): void {
  authToken = token
}

http.interceptors.request.use((config) => {
  if (authToken) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${authToken}`
  }
  return config
})

// A single hook fired when a *guarded* call comes back 401 (an expired/cleared
// token mid-session). useAuth wires it to logout + redirect. Kept as a plain
// callback rather than importing the router here, to avoid an api<->router cycle.
// 401s from /auth/* (wrong password on the login form, or a stale token probed by
// fetchMe on boot) are the caller's to handle, so they never trip the global hook.
let onUnauthorized: (() => void) | null = null
export function setOnUnauthorized(fn: (() => void) | null): void {
  onUnauthorized = fn
}

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const status = error.response?.status
    const url = error.config?.url ?? ''
    if (status === 401 && !url.startsWith('/auth/') && onUnauthorized) {
      onUnauthorized()
    }
    return Promise.reject(error)
  },
)

// --- Auth endpoints (TASK-027) ------------------------------------------------
// POST /auth/register -- create an account, returns a token + the new user.
export async function registerUser(email: string, password: string): Promise<AuthTokenResponse> {
  const { data } = await http.post<AuthTokenResponse>('/auth/register', { email, password })
  return data
}

// POST /auth/login -- exchange credentials for a token + user.
export async function loginUser(email: string, password: string): Promise<AuthTokenResponse> {
  const { data } = await http.post<AuthTokenResponse>('/auth/login', { email, password })
  return data
}

// GET /auth/me -- the current user for the attached token (validates it on boot).
export async function fetchMe(): Promise<AuthUser> {
  const { data } = await http.get<AuthUser>('/auth/me')
  return data
}

// POST /sessions -- multipart upload. The form field MUST be named `file`
// (matches create_session's `file: UploadFile = File(...)`).
export async function createSession(file: File): Promise<SessionInfo> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<SessionInfo>('/sessions', form)
  return data
}

// POST /sessions/{id}/tables -- add a SECOND (or further) table to an existing session.
// Multipart; the form field MUST be named `file` (matches upload_table). The table is
// registered with is_primary=false, so the session then holds multiple tables the user
// can switch between (ADR-006: switcher only, no cross-table joins).
export async function uploadTable(sessionUuid: string, file: File): Promise<TableUploadResponse> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<TableUploadResponse>(`/sessions/${sessionUuid}/tables`, form)
  return data
}

export interface FetchDataParams {
  offset: number
  limit: number
  tableName?: string
  // TASK-022: server-side multi-sort (serialized to "col:dir,...") and a
  // substring search term (sent as `q`). Both optional ⇒ unchanged behaviour.
  sort?: SortSpec[]
  search?: string
}

// GET /sessions/{id}/data?offset&limit&table_name&sort&q -- one windowed page.
export async function fetchData(
  sessionUuid: string,
  params: FetchDataParams,
): Promise<DataResponse> {
  const sort = (params.sort ?? []).map((s) => `${s.column}:${s.dir}`).join(',')
  const search = (params.search ?? '').trim()
  const { data } = await http.get<DataResponse>(`/sessions/${sessionUuid}/data`, {
    params: {
      offset: params.offset,
      limit: params.limit,
      ...(params.tableName ? { table_name: params.tableName } : {}),
      ...(sort ? { sort } : {}),
      ...(search ? { q: search } : {}),
    },
  })
  return data
}

// FastAPI raises HTTPException{detail} (e.g. the 404 from _resolve_table); our
// custom error bodies use {message}. Fall back to the transport-level message.
export function apiErrorMessage(e: unknown): string {
  const err = e as AxiosError<{ detail?: string; message?: string }>
  return (
    err.response?.data?.detail ??
    err.response?.data?.message ??
    err.message ??
    'Request failed'
  )
}

// A blob-typed request (exportTable/exportRows) that FAILS carries its error body as a
// Blob, not parsed JSON -- read it back so the {detail}/{message} still surfaces. Async
// (Blob.text() is a promise); falls back to the transport message.
export async function blobErrorMessage(e: unknown): Promise<string> {
  const err = e as AxiosError
  const data = err.response?.data as unknown
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text()) as { detail?: string; message?: string }
      return parsed.detail ?? parsed.message ?? err.message ?? 'Export failed'
    } catch {
      return err.message ?? 'Export failed'
    }
  }
  return apiErrorMessage(e)
}

// Every cleaning/history call accepts an optional ?table_name (defaults to the
// session's primary table server-side); only send it when set.
function tableParam(tableName?: string): Record<string, string> {
  return tableName ? { table_name: tableName } : {}
}

// POST /sessions/{id}/transform -- apply one cleaning op (body = TransformOp union).
export async function applyTransform(
  sessionUuid: string,
  op: TransformOp,
  tableName?: string,
): Promise<TransformResponse> {
  const { data } = await http.post<TransformResponse>(
    `/sessions/${sessionUuid}/transform`,
    op,
    { params: tableParam(tableName) },
  )
  return data
}

// POST /sessions/{id}/transform/preview -- dry run; no materialize, no version bump.
export async function previewTransform(
  sessionUuid: string,
  op: TransformOp,
  tableName?: string,
): Promise<TransformPreviewResponse> {
  const { data } = await http.post<TransformPreviewResponse>(
    `/sessions/${sessionUuid}/transform/preview`,
    op,
    { params: tableParam(tableName) },
  )
  return data
}

// POST /sessions/{id}/undo | /redo -- step through the snapshot history (cap 10).
export async function undoTransform(
  sessionUuid: string,
  tableName?: string,
): Promise<TransformResponse> {
  const { data } = await http.post<TransformResponse>(
    `/sessions/${sessionUuid}/undo`,
    null,
    { params: tableParam(tableName) },
  )
  return data
}

export async function redoTransform(
  sessionUuid: string,
  tableName?: string,
): Promise<TransformResponse> {
  const { data } = await http.post<TransformResponse>(
    `/sessions/${sessionUuid}/redo`,
    null,
    { params: tableParam(tableName) },
  )
  return data
}

// GET /sessions/{id}/history -- steps + can_undo/can_redo state.
export async function fetchHistory(
  sessionUuid: string,
  tableName?: string,
): Promise<HistoryResponse> {
  const { data } = await http.get<HistoryResponse>(
    `/sessions/${sessionUuid}/history`,
    { params: tableParam(tableName) },
  )
  return data
}

// GET /sessions/{id}/schema -- live column list, recomputed after every transform.
export async function fetchSchema(sessionUuid: string): Promise<SchemaResponse> {
  const { data } = await http.get<SchemaResponse>(`/sessions/${sessionUuid}/schema`)
  return data
}

// POST /sessions/{id}/aggregate -- one Canvas KPI (no dimension) or chart series
// (dimension set). Typed params only; the backend Ibis-compiles the SQL against the
// live schema, so nothing here is string-built into a query (ADR-012).
export async function fetchAggregate(
  sessionUuid: string,
  req: AggregateRequest,
  tableName?: string,
): Promise<AggregateResponse> {
  const { data } = await http.post<AggregateResponse>(
    `/sessions/${sessionUuid}/aggregate`,
    req,
    { params: tableParam(tableName) },
  )
  return data
}

// GET /sessions/{id}/profile/column?column&table_name -- one column's statistical
// profile (completeness + kind-appropriate detail) for the Table data-prep panel.
// Read-only; the backend Ibis-compiles every SELECT from the column name validated
// against the live schema (ADR-012). `column` is a required query param.
export async function fetchColumnProfile(
  sessionUuid: string,
  column: string,
  tableName?: string,
): Promise<ColumnProfile> {
  const { data } = await http.get<ColumnProfile>(
    `/sessions/${sessionUuid}/profile/column`,
    { params: { column, ...tableParam(tableName) } },
  )
  return data
}

// GET /sessions/{id}/quality?table_name -- whole-table data-quality scan (ranked
// findings, each with an optional one-click Fix). Read-only; no column input from the
// client -- the backend enumerates columns from the live schema and Ibis-compiles the
// battery of checks (ADR-012). Re-fetched on every transform to re-assess.
export async function fetchQualityReport(
  sessionUuid: string,
  tableName?: string,
): Promise<QualityReport> {
  const { data } = await http.get<QualityReport>(
    `/sessions/${sessionUuid}/quality`,
    { params: tableParam(tableName) },
  )
  return data
}

// --- Query Engine (Phase 6 / TASK-012) ---

// POST /sessions/{id}/ask -- NL question -> generated SQL (the Review Gate). The SQL
// is RETURNED for the user to inspect and run; this call never executes it. An optional
// `history` of prior (question, sql) turns lets a follow-up refine the last query (#21);
// with no history the body is byte-identical to before, so pre-#21 cache entries hit.
export async function askQuestion(
  sessionUuid: string,
  question: string,
  history?: AskTurn[],
): Promise<AskResponse> {
  const { data } = await http.post<AskResponse>(`/sessions/${sessionUuid}/ask`, {
    question,
    ...(history && history.length ? { history } : {}),
  })
  return data
}

// --- Query Engine AI assists (Wave 4) ---

// POST /sessions/{id}/sql/assist -- explain / fix / optimize the editor's SQL (#22).
// `fix` passes the DuckDB error text; explain/optimize ignore it. fix/optimize return a
// NEW validated SELECT for the Review Gate (never auto-run); explain returns sql=null.
export async function sqlAssist(
  sessionUuid: string,
  mode: SqlAssistMode,
  sql: string,
  error?: string | null,
): Promise<SqlAssistResponse> {
  const { data } = await http.post<SqlAssistResponse>(
    `/sessions/${sessionUuid}/sql/assist`,
    { mode, sql, ...(error ? { error } : {}) },
  )
  return data
}

// GET /sessions/{id}/suggest-questions -- analytical questions inferred from the schema
// (#26 auto-EDA), each ready to drop into /ask. Cached per schema_version server-side.
export async function suggestQuestions(
  sessionUuid: string,
): Promise<SuggestQuestionsResponse> {
  const { data } = await http.get<SuggestQuestionsResponse>(
    `/sessions/${sessionUuid}/suggest-questions`,
  )
  return data
}

// GET /sessions/{id}/narrate -- a plain-prose overview of the loaded dataset (#29).
export async function narrateDataset(sessionUuid: string): Promise<NarrativeResponse> {
  const { data } = await http.get<NarrativeResponse>(`/sessions/${sessionUuid}/narrate`)
  return data
}

// POST /sessions/{id}/recommend-chart -- a chart-type suggestion for one column (#30).
// `column`/`columnType` are prompt context only; no SQL is built from them.
export async function recommendChart(
  sessionUuid: string,
  column: string,
  columnType?: string | null,
  intent?: string | null,
): Promise<RecommendChartResponse> {
  const { data } = await http.post<RecommendChartResponse>(
    `/sessions/${sessionUuid}/recommend-chart`,
    { column, ...(columnType ? { column_type: columnType } : {}), ...(intent ? { intent } : {}) },
  )
  return data
}

// POST /sessions/{id}/explain-chart -- narrate one Canvas chart from the aggregate the
// tile already holds (#18). No new query runs; keys/values are prompt context only.
export async function explainChart(
  sessionUuid: string,
  spec: ExplainChartRequest,
): Promise<NarrativeResponse> {
  const { data } = await http.post<NarrativeResponse>(
    `/sessions/${sessionUuid}/explain-chart`,
    spec,
  )
  return data
}

// POST /sessions/{id}/execute -- run a user-reviewed SELECT; rows come back as JSON.
// The backend validates (fail-closed) and runs it inside a rolled-back sandbox.
export async function executeSql(
  sessionUuid: string,
  sql: string,
): Promise<ExecuteResultResponse> {
  const { data } = await http.post<ExecuteResultResponse>(
    `/sessions/${sessionUuid}/execute`,
    { sql },
  )
  return data
}

// GET /sessions/{id}/instructions -- list the business dictionary (term -> definition).
export async function fetchInstructions(sessionUuid: string): Promise<CustomInstruction[]> {
  const { data } = await http.get<CustomInstruction[]>(`/sessions/${sessionUuid}/instructions`)
  return data
}

// POST /sessions/{id}/instructions -- add/update one term (bumps bizdict_version).
export async function addInstruction(
  sessionUuid: string,
  instruction: CustomInstruction,
): Promise<void> {
  await http.post(`/sessions/${sessionUuid}/instructions`, instruction)
}

// DELETE /sessions/{id}/instructions/{term} -- remove one term (bumps bizdict_version).
export async function deleteInstruction(sessionUuid: string, term: string): Promise<void> {
  await http.delete(`/sessions/${sessionUuid}/instructions/${encodeURIComponent(term)}`)
}

// --- Export (Round-trip data, Wave 2 / TASK-020) ---

export type ExportFormat = 'csv' | 'tsv' | 'json' | 'parquet' | 'xlsx'

// GET /sessions/{id}/export?format&table_name -- download the whole cleaned table as a
// binary blob (the server encodes via DuckDB COPY / openpyxl). The caller names the file.
export async function exportTable(
  sessionUuid: string,
  format: ExportFormat,
  tableName?: string,
): Promise<Blob> {
  const { data } = await http.get(`/sessions/${sessionUuid}/export`, {
    params: { format, ...(tableName ? { table_name: tableName } : {}) },
    responseType: 'blob',
  })
  return data
}

// POST /sessions/{id}/export/rows -- encode query-result rows already in hand to .xlsx
// (CSV/JSON/clipboard are done client-side). Rows travel as JSON, keyed by column name.
export async function exportRows(
  sessionUuid: string,
  columns: string[],
  rows: Record<string, unknown>[],
): Promise<Blob> {
  const { data } = await http.post(
    `/sessions/${sessionUuid}/export/rows`,
    { columns, rows, format: 'xlsx' },
    { responseType: 'blob' },
  )
  return data
}
