// Module-scoped singleton: one shared session across sibling components without
// Pinia (the app has exactly one active session at a time). UploadDropzone
// writes it; DataGrid reads it. `state` lives at module scope, so every
// useSession() call returns refs into the *same* reactive object.
import { reactive, toRefs } from 'vue'
import type { ColumnMeta } from '../types'
import { createSession, apiErrorMessage } from '../services/api'

interface SessionState {
  sessionUuid: string | null
  tableName: string | null
  columns: ColumnMeta[]
  rowCount: number
  uploading: boolean
  error: string | null
}

const state = reactive<SessionState>({
  sessionUuid: null,
  tableName: null,
  columns: [],
  rowCount: 0,
  uploading: false,
  error: null,
})

async function upload(file: File): Promise<void> {
  state.uploading = true
  state.error = null
  try {
    const info = await createSession(file)
    state.sessionUuid = info.session_uuid
    state.tableName = info.table_name
    state.columns = info.columns
    state.rowCount = info.row_count
  } catch (e) {
    // Clear the session on failure so the grid falls back to its empty state
    // instead of trying to page a table that was never created.
    state.error = apiErrorMessage(e)
    state.sessionUuid = null
  } finally {
    state.uploading = false
  }
}

export function useSession() {
  return { ...toRefs(state), upload }
}
