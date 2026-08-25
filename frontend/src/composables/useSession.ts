// Module-scoped singleton: one shared session across sibling components without
// Pinia (the app has exactly one active session at a time). UploadDropzone writes
// it; DataGrid, the cleaning toolbar and per-column menus read + mutate it. `state`
// lives at module scope, so every useSession() call returns refs into the *same*
// reactive object.
import { reactive, toRefs } from 'vue'
import type { ColumnMeta, TransformOp, HistoryStep, SchemaTable } from '../types'
import {
  createSession,
  uploadTable,
  applyTransform,
  undoTransform,
  redoTransform,
  fetchHistory,
  fetchSchema,
  fetchData,
  apiErrorMessage,
} from '../services/api'

interface SessionState {
  sessionUuid: string | null
  tableName: string | null
  fileName: string | null
  columns: ColumnMeta[]
  // Every table loaded in this session (the primary plus any added via addTable);
  // drives the multi-table switcher. `tableName` names which one is active. Per
  // ADR-006 this is a *switcher* — the app acts on one table at a time, no joins.
  tables: SchemaTable[]
  rowCount: number
  uploading: boolean
  applying: boolean
  error: string | null
  // True while restoreSession() is validating a persisted pointer against the server
  // on app start. Lets the UI show a "restoring…" placeholder instead of flashing the
  // empty upload screen before the rehydrated session lands.
  restoring: boolean
  // Bumped after every applied transform / undo / redo so the grid refetches from
  // offset 0. Session switches are handled separately by DataGrid's sessionUuid watch.
  dataVersion: number
  canUndo: boolean
  canRedo: boolean
  historySteps: HistoryStep[]
}

const state = reactive<SessionState>({
  sessionUuid: null,
  tableName: null,
  fileName: null,
  columns: [],
  tables: [],
  rowCount: 0,
  uploading: false,
  applying: false,
  error: null,
  restoring: false,
  dataVersion: 0,
  canUndo: false,
  canRedo: false,
  historySteps: [],
})

// --- Session persistence across page reloads --------------------------------
// The dataset itself is durable server-side: the table lives in DuckDB (a single
// on-disk file) and the session→schema mapping lives in Redis (with a sliding TTL).
// Only the frontend's *pointer* to that session was ephemeral, so a refresh dropped
// back to the empty upload screen. We stash the session identity (uuid + primary
// table + original file name) in localStorage on upload and rehydrate it on app
// start (restoreSession), mirroring how dashboards/saved-queries already persist.
// Columns and row count are deliberately NOT stored — they go stale after a
// transform — they are re-fetched live from the schema during restore.
const PERSIST_KEY = 'spencer.activeSession.v1'

interface PersistedSession {
  sessionUuid: string
  tableName: string | null
  fileName: string | null
}

function persistSession(): void {
  try {
    if (!state.sessionUuid) {
      localStorage.removeItem(PERSIST_KEY)
      return
    }
    const payload: PersistedSession = {
      sessionUuid: state.sessionUuid,
      tableName: state.tableName,
      fileName: state.fileName,
    }
    localStorage.setItem(PERSIST_KEY, JSON.stringify(payload))
  } catch {
    // localStorage may be unavailable (private mode / quota). Persistence is a
    // convenience, so a failure here must never break the upload flow.
  }
}

function clearPersisted(): void {
  try {
    localStorage.removeItem(PERSIST_KEY)
  } catch {
    /* ignore — see persistSession */
  }
}

function readPersisted(): PersistedSession | null {
  try {
    const raw = localStorage.getItem(PERSIST_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<PersistedSession>
    if (!parsed || typeof parsed.sessionUuid !== 'string') return null
    return {
      sessionUuid: parsed.sessionUuid,
      tableName: typeof parsed.tableName === 'string' ? parsed.tableName : null,
      fileName: typeof parsed.fileName === 'string' ? parsed.fileName : null,
    }
  } catch {
    return null
  }
}

// True 404 from the API (session expired/swept or backend reset) vs. a transient
// network/5xx error. Only a 404 means the pointer is definitively dead.
function isNotFound(e: unknown): boolean {
  return (
    !!e &&
    typeof e === 'object' &&
    'response' in e &&
    (e as { response?: { status?: number } }).response?.status === 404
  )
}

// Set the first-render flag synchronously (at module load, before any component
// mounts) so a pending restore shows a placeholder instead of the upload screen.
state.restoring = readPersisted() !== null

// Drop back to the empty state so the upload dropzone reappears (the "Replace" path).
// Also used on logout (TASK-027): clears the active-session pointer so the next user
// never inherits the previous user's session, and re-arms restoreSession so a
// subsequent login can rehydrate that user's own session.
function resetSession(): void {
  state.sessionUuid = null
  state.tableName = null
  state.fileName = null
  state.columns = []
  state.tables = []
  state.rowCount = 0
  state.error = null
  state.canUndo = false
  state.canRedo = false
  state.historySteps = []
  clearPersisted()
  restoreAttempted = false
  // dataVersion stays monotonic; consumers key off the change, not the value.
}

async function upload(file: File): Promise<void> {
  state.uploading = true
  state.error = null
  try {
    const info = await createSession(file)
    state.sessionUuid = info.session_uuid
    state.tableName = info.table_name
    state.fileName = file.name
    state.columns = info.columns
    state.rowCount = info.row_count
    // Fresh session: exactly one (primary) table. The switcher list starts here and
    // grows as addTable() adds more.
    state.tables = [{ table_name: info.table_name, is_primary: true, columns: info.columns }]
    state.canUndo = false
    state.canRedo = false
    state.historySteps = []
    // Remember this session so a page refresh restores it (see restoreSession).
    persistSession()
  } catch (e) {
    // Clear the session on failure so the grid falls back to its empty state
    // instead of trying to page a table that was never created.
    state.error = apiErrorMessage(e)
    state.sessionUuid = null
  } finally {
    state.uploading = false
  }
}

// Refresh undo/redo availability from the server-side history.
async function refreshHistory(): Promise<void> {
  const uuid = state.sessionUuid
  if (!uuid) return
  try {
    const h = await fetchHistory(uuid, state.tableName ?? undefined)
    state.canUndo = h.can_undo
    state.canRedo = h.can_redo
    state.historySteps = h.steps
  } catch {
    // History is advisory (drives button enablement); ignore transient failures.
  }
}

// After any table mutation, resync row count + live schema (transforms can add,
// drop, rename or retype columns), refresh undo/redo state, then bump dataVersion
// so the grid reloads its first window.
async function syncAfterMutation(rowCount: number): Promise<void> {
  const uuid = state.sessionUuid
  if (!uuid) return
  state.rowCount = rowCount
  try {
    const schema = await fetchSchema(uuid)
    state.tables = schema.tables
    // Keep the ACTIVE table's columns (prefer the switched-to table over primary), so a
    // transform on a secondary table resyncs that table's schema — not primary's.
    const active =
      schema.tables.find((t) => t.table_name === state.tableName) ??
      schema.tables.find((t) => t.is_primary) ??
      schema.tables[0]
    if (active) state.columns = active.columns
  } catch {
    // Non-fatal: keep the prior column list if the schema refresh fails.
  }
  await refreshHistory()
  state.dataVersion++
}

// Apply a cleaning op. Returns true on success so the caller (OpDialog) can close;
// on failure the error is surfaced via state.error and the dialog stays open.
async function applyOp(op: TransformOp): Promise<boolean> {
  const uuid = state.sessionUuid
  if (!uuid || state.applying) return false
  state.applying = true
  state.error = null
  try {
    const resp = await applyTransform(uuid, op, state.tableName ?? undefined)
    await syncAfterMutation(resp.row_count)
    return true
  } catch (e) {
    state.error = apiErrorMessage(e)
    return false
  } finally {
    state.applying = false
  }
}

async function undo(): Promise<void> {
  const uuid = state.sessionUuid
  if (!uuid || state.applying || !state.canUndo) return
  state.applying = true
  state.error = null
  try {
    const resp = await undoTransform(uuid, state.tableName ?? undefined)
    await syncAfterMutation(resp.row_count)
  } catch (e) {
    state.error = apiErrorMessage(e)
  } finally {
    state.applying = false
  }
}

async function redo(): Promise<void> {
  const uuid = state.sessionUuid
  if (!uuid || state.applying || !state.canRedo) return
  state.applying = true
  state.error = null
  try {
    const resp = await redoTransform(uuid, state.tableName ?? undefined)
    await syncAfterMutation(resp.row_count)
  } catch (e) {
    state.error = apiErrorMessage(e)
  } finally {
    state.applying = false
  }
}

// Run once at app start (App.vue onMounted): if a session was persisted, validate it
// against the server and rehydrate the singleton so a refresh returns to the loaded
// table instead of the empty upload screen. Guards:
//  - no stored pointer            -> nothing to do, clear the restoring flag.
//  - schema 404 (session gone)    -> forget the dead pointer, show the upload screen.
//  - network/5xx (backend down)   -> KEEP the pointer (a later reload can still restore)
//                                    and just fall back to empty for now.
let restoreAttempted = false
async function restoreSession(): Promise<void> {
  if (restoreAttempted) return // App mounts once, but stay idempotent regardless.
  restoreAttempted = true
  const stored = readPersisted()
  if (!stored) {
    state.restoring = false
    return
  }
  state.restoring = true
  try {
    // Existence check + live column source in one call (404s cleanly if gone).
    const schema = await fetchSchema(stored.sessionUuid)
    // Prefer the persisted ACTIVE table (so a refresh returns to the table you switched
    // to, not primary); fall back to primary, then the first table.
    const active =
      schema.tables.find((t) => t.table_name === stored.tableName) ??
      schema.tables.find((t) => t.is_primary) ??
      schema.tables[0]
    if (!active) {
      // Session resolved but has no tables — treat as gone.
      clearPersisted()
      return
    }
    // The schema carries no row count; a 1-row page's `total` is the table total.
    let rowCount = 0
    try {
      const page = await fetchData(stored.sessionUuid, { offset: 0, limit: 1 })
      rowCount = page.total
    } catch {
      // Best-effort: the grid re-derives the true total from its own first fetch.
    }
    // Populate identity/columns BEFORE sessionUuid so every consumer that watches
    // sessionUuid (grid, quality panel, suggestions) sees a coherent session at once.
    state.tableName = active.table_name
    state.fileName = stored.fileName
    state.columns = active.columns
    state.tables = schema.tables
    state.rowCount = rowCount
    state.sessionUuid = stored.sessionUuid
    // Re-persist in case the primary table name drifted from what was stored.
    persistSession()
    await refreshHistory()
  } catch (e) {
    if (isNotFound(e)) clearPersisted()
    // Transient errors keep the pointer for a future retry; nothing else to restore.
  } finally {
    state.restoring = false
  }
}

// --- Multi-table switching (TASK-039) --------------------------------------
// Point the whole app (grid, data-prep, Canvas field lists, Query schema) at a
// different already-loaded table in this session: set the active name + its live
// columns and reload that table's undo/redo history. Deliberately does NOT bump
// dataVersion — that signal means "the active table's rows/schema changed" and makes
// ChartCanvas re-run every tile, so a table *switch* must not silently re-point
// existing charts. The grid reloads via its own watch(tableName); Canvas/Query read
// the new `columns` reactively for any NEW tiles/queries.
function setActiveTable(name: string): void {
  if (!state.sessionUuid || name === state.tableName) return
  const t = state.tables.find((x) => x.table_name === name)
  if (!t) return
  state.tableName = t.table_name
  state.columns = t.columns
  persistSession()
  void refreshHistory()
}

// Add another table to the current session (secondary; is_primary=false server-side),
// then make it active. Re-reads the schema so the switcher lists the new table with its
// live columns. Returns true on success; the error (e.g. duplicate table name, bad file)
// is surfaced via state.error for the caller to show.
async function addTable(file: File): Promise<boolean> {
  const uuid = state.sessionUuid
  if (!uuid || state.uploading) return false
  state.uploading = true
  state.error = null
  try {
    const resp = await uploadTable(uuid, file)
    const schema = await fetchSchema(uuid)
    state.tables = schema.tables
    setActiveTable(resp.table_name)
    return true
  } catch (e) {
    state.error = apiErrorMessage(e)
    return false
  } finally {
    state.uploading = false
  }
}

export function useSession() {
  return {
    ...toRefs(state),
    upload,
    addTable,
    setActiveTable,
    applyOp,
    undo,
    redo,
    refreshHistory,
    resetSession,
    restoreSession,
  }
}
