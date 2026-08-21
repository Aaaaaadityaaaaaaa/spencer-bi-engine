// Single Axios client for the backend. Absolute baseURL (not a Vite proxy) so
// the browser talks to the API host directly; the backend CORS config already
// allows the :5173 dev origin. Override with VITE_API_BASE at build/dev time.
import axios from 'axios'
import type { AxiosError } from 'axios'
import type { SessionInfo, DataResponse } from '../types'

const baseURL = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

const http = axios.create({ baseURL })

// POST /sessions -- multipart upload. The form field MUST be named `file`
// (matches create_session's `file: UploadFile = File(...)`).
export async function createSession(file: File): Promise<SessionInfo> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<SessionInfo>('/sessions', form)
  return data
}

export interface FetchDataParams {
  offset: number
  limit: number
  tableName?: string
}

// GET /sessions/{id}/data?offset&limit&table_name -- one windowed page of rows.
export async function fetchData(
  sessionUuid: string,
  params: FetchDataParams,
): Promise<DataResponse> {
  const { data } = await http.get<DataResponse>(`/sessions/${sessionUuid}/data`, {
    params: {
      offset: params.offset,
      limit: params.limit,
      ...(params.tableName ? { table_name: params.tableName } : {}),
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
