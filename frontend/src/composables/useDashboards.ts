// Saved dashboards, persisted in localStorage (TASK-026 / Wave 6, feature #15; multi-page
// since TASK-034, wired into the Canvas by TASK-035).
//
// A "dashboard" is just the set of PAGES on the Canvas -- each a set of tile CONFIGS
// (KPI + chart specs) plus their grid layout -- no fetched data, no per-tile loading
// state. Saving snapshots those configs; loading hands them back to ChartCanvas, which
// re-runs every aggregation against whatever dataset is currently loaded. That decoupling
// is deliberate: a saved layout is portable across dataset re-uploads (as long as the
// column names still exist), exactly like a saved SQL query in useQueryHistory.
//
// Same shape as useQueryHistory on purpose: a module-scoped reactive singleton, tolerant
// load, swallow-on-quota persist, `${Date.now()}-${counter}` ids. Client-side only --
// this is a single-user app, so there is no backend persistence to coordinate with.
import { reactive, toRefs } from 'vue'
import type { DashboardSnapshot, SavedDashboard } from '../types'

const SAVED_KEY = 'spencer.savedDashboards'

interface DashboardState {
  dashboards: SavedDashboard[]
}

// Per-user key namespacing (TASK-027): a shared browser must never leak one user's
// saved dashboards to another. The active user id (set by useAuth via loadForUser)
// suffixes the storage key; with no user the store stays empty.
let currentUserId: string | null = null
function k(base: string): string {
  return currentUserId ? `${base}:${currentUserId}` : base
}

// A saved row is trusted only if it carries the multi-page shape (id/name/savedAt + a
// `pages` array + activePageId). The store was reshaped single-page → multi-page in
// TASK-034 while orphaned (wired into no UI), so no real single-page rows were ever
// written to disk — a shape-mismatched row is therefore treated as corrupt and dropped,
// not migrated. This keeps loadDashboard from handing the Canvas a page-less snapshot.
function isValidSaved(row: unknown): row is SavedDashboard {
  if (!row || typeof row !== 'object') return false
  const r = row as Record<string, unknown>
  return (
    typeof r.id === 'string' &&
    typeof r.name === 'string' &&
    typeof r.savedAt === 'string' &&
    Array.isArray(r.pages) &&
    typeof r.activePageId === 'string'
  )
}

// Load the persisted list, tolerating absent/corrupt/rejected storage (private mode,
// hand-edited values) by starting clean rather than throwing at import time; shape-invalid
// rows are filtered out (see isValidSaved).
function loadArray(key: string): SavedDashboard[] {
  if (typeof localStorage === 'undefined') return []
  try {
    const raw = localStorage.getItem(key)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter(isValidSaved) : []
  } catch {
    return []
  }
}

// State starts EMPTY (no import-time global-key read); useAuth calls loadForUser once
// the active user is known.
const state = reactive<DashboardState>({
  dashboards: [],
})

// Switch the store to a user's namespace: replace the in-memory list with that user's
// persisted dashboards, or clear on logout (userId === null). Per-user keys stay on
// disk so a re-login restores them.
export function loadForUser(userId: string | null): void {
  currentUserId = userId
  state.dashboards = userId ? loadArray(k(SAVED_KEY)) : []
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

let counter = 0
function makeId(): string {
  counter += 1
  return `${Date.now().toString(36)}-${counter}`
}

// Deep-copy a snapshot so the stored value is severed from the live reactive Canvas
// arrays -- otherwise a later tile edit would silently mutate the "saved" dashboard,
// and re-loading would hand back proxies that alias the current tiles. JSON round-trip
// is sufficient: pages/configs/layouts are plain data (strings/numbers/null), no
// functions or dates.
function cloneSnapshot(snapshot: DashboardSnapshot): DashboardSnapshot {
  return JSON.parse(JSON.stringify({ pages: snapshot.pages, activePageId: snapshot.activePageId }))
}

// Save the current Canvas as a new named dashboard (newest first). No-op on a blank
// name. Duplicate names are allowed -- the id is the identity, the name is just a label.
function saveDashboard(name: string, snapshot: DashboardSnapshot): SavedDashboard | null {
  const clean = name.trim()
  if (!clean) return null
  const copy = cloneSnapshot(snapshot)
  const row: SavedDashboard = {
    id: makeId(),
    name: clean,
    savedAt: new Date().toISOString(),
    pages: copy.pages,
    activePageId: copy.activePageId,
  }
  state.dashboards = [row, ...state.dashboards]
  persist(k(SAVED_KEY), state.dashboards)
  return row
}

// Return a fresh deep copy of a saved dashboard's pages (or null if the id is gone),
// so the caller can seed the Canvas without aliasing the stored record.
function loadDashboard(id: string): DashboardSnapshot | null {
  const found = state.dashboards.find((d) => d.id === id)
  if (!found) return null
  return cloneSnapshot(found)
}

function renameDashboard(id: string, name: string): void {
  const clean = name.trim()
  if (!clean) return
  state.dashboards = state.dashboards.map((d) => (d.id === id ? { ...d, name: clean } : d))
  persist(k(SAVED_KEY), state.dashboards)
}

function deleteDashboard(id: string): void {
  state.dashboards = state.dashboards.filter((d) => d.id !== id)
  persist(k(SAVED_KEY), state.dashboards)
}

export function useDashboards() {
  return { ...toRefs(state), saveDashboard, loadDashboard, renameDashboard, deleteDashboard }
}
