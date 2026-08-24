// Query Engine history + saved queries, persisted in localStorage. This is a purely
// client-side convenience layer (no backend, no session coupling): recent runs and
// bookmarked queries survive a page reload and a dataset swap, since a user often
// re-runs the same SQL against a re-uploaded file. Module-scoped singleton like
// useSession, so the console and the history panel read/write ONE reactive store.
import { reactive, toRefs } from 'vue'

export interface QueryHistoryEntry {
  id: string
  sql: string
  question: string | null // the NL prompt, when the SQL came from "Generate SQL"
  ranAt: string // ISO timestamp
  ok: boolean
  rowCount: number | null
  error: string | null
}

export interface SavedQuery {
  id: string
  name: string
  sql: string
  savedAt: string
}

const HISTORY_KEY = 'spencer.queryHistory'
const SAVED_KEY = 'spencer.savedQueries'
const HISTORY_CAP = 30 // keep the most recent N runs; older ones roll off

interface HistoryState {
  history: QueryHistoryEntry[]
  saved: SavedQuery[]
}

// Per-user key namespacing (TASK-027): a shared browser must never leak one user's
// history/saved queries to another. The active user id (set by useAuth via
// loadForUser) suffixes every storage key; with no user the store stays empty.
let currentUserId: string | null = null
function k(base: string): string {
  return currentUserId ? `${base}:${currentUserId}` : base
}

// Load a persisted array, tolerating absent/corrupt/rejected storage (private mode,
// hand-edited values) by starting clean rather than throwing at import time.
function loadArray<T>(key: string): T[] {
  if (typeof localStorage === 'undefined') return []
  try {
    const raw = localStorage.getItem(key)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? (parsed as T[]) : []
  } catch {
    return []
  }
}

// State starts EMPTY (no import-time global-key read); useAuth calls loadForUser once
// the active user is known, so nothing loads before we know whose data it is.
const state = reactive<HistoryState>({
  history: [],
  saved: [],
})

// Switch the store to a user's namespace: replace (not append) the in-memory arrays
// with that user's persisted data, or clear them on logout (userId === null). The
// per-user keys are left on disk so a re-login restores them.
export function loadForUser(userId: string | null): void {
  currentUserId = userId
  state.history = userId ? loadArray<QueryHistoryEntry>(k(HISTORY_KEY)) : []
  state.saved = userId ? loadArray<SavedQuery>(k(SAVED_KEY)) : []
}

function persist(key: string, value: unknown): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Quota/permission errors are non-fatal: the in-memory store still works this
    // session; it just won't survive a reload.
  }
}

// A small unique id. Date.now() is browser-only (fine here -- the Workflow-script
// restriction does not apply to app code); the counter breaks ties within one ms.
let counter = 0
function makeId(): string {
  counter += 1
  return `${Date.now().toString(36)}-${counter}`
}

// Record one executed query. Called on BOTH success and failure so the history is an
// honest log of what actually ran, not just what worked.
function recordRun(entry: {
  sql: string
  question?: string | null
  ok: boolean
  rowCount?: number | null
  error?: string | null
}): void {
  const row: QueryHistoryEntry = {
    id: makeId(),
    sql: entry.sql,
    question: entry.question ?? null,
    ranAt: new Date().toISOString(),
    ok: entry.ok,
    rowCount: entry.rowCount ?? null,
    error: entry.error ?? null,
  }
  state.history = [row, ...state.history].slice(0, HISTORY_CAP) // newest first
  persist(k(HISTORY_KEY), state.history)
}

function clearHistory(): void {
  state.history = []
  persist(k(HISTORY_KEY), state.history)
}

function saveQuery(name: string, sql: string): void {
  const clean = name.trim()
  if (!clean || !sql.trim()) return
  const row: SavedQuery = { id: makeId(), name: clean, sql, savedAt: new Date().toISOString() }
  state.saved = [row, ...state.saved]
  persist(k(SAVED_KEY), state.saved)
}

function deleteSaved(id: string): void {
  state.saved = state.saved.filter((q) => q.id !== id)
  persist(k(SAVED_KEY), state.saved)
}

export function useQueryHistory() {
  return { ...toRefs(state), recordRun, clearHistory, saveQuery, deleteSaved }
}
