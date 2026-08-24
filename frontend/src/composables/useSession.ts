// Module-scoped singleton: one shared session across sibling components without
// Pinia (the app has exactly one active session at a time). UploadDropzone writes
// it; DataGrid, the cleaning toolbar and per-column menus read + mutate it. `state`
// lives at module scope, so every useSession() call returns refs into the *same*
// reactive object.
import { reactive, toRefs } from 'vue'
import type { ColumnMeta, TransformOp, HistoryStep } from '../types'
import {
  createSession,
  applyTransform,
  undoTransform,
  redoTransform,
  fetchHistory,
  fetchSchema,
  apiErrorMessage,
} from '../services/api'

interface SessionState {
  sessionUuid: string | null
  tableName: string | null
  fileName: string | null
  columns: ColumnMeta[]
  rowCount: number
  uploading: boolean
  applying: boolean
  error: string | null
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
  rowCount: 0,
  uploading: false,
  applying: false,
  error: null,
  dataVersion: 0,
  canUndo: false,
  canRedo: false,
  historySteps: [],
})

// Drop back to the empty state so the upload dropzone reappears (the "Replace" path).
function resetSession(): void {
  state.sessionUuid = null
  state.tableName = null
  state.fileName = null
  state.columns = []
  state.rowCount = 0
  state.error = null
  state.canUndo = false
  state.canRedo = false
  state.historySteps = []
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
    state.canUndo = false
    state.canRedo = false
    state.historySteps = []
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
    const primary =
      schema.tables.find((t) => t.is_primary) ??
      schema.tables.find((t) => t.table_name === state.tableName) ??
      schema.tables[0]
    if (primary) state.columns = primary.columns
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

export function useSession() {
  return { ...toRefs(state), upload, applyOp, undo, redo, refreshHistory, resetSession }
}
