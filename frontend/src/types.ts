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
}
