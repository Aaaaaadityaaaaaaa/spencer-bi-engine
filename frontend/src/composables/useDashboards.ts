// Saved dashboards, persisted in localStorage (TASK-026 / Wave 6, feature #15).
//
// A "dashboard" is just the set of tile CONFIGS on the Canvas (KPI + chart specs) --
// no fetched data, no per-tile loading state. Saving snapshots those configs; loading
// hands them back to ChartCanvas, which re-runs every aggregation against whatever
// dataset is currently loaded. That decoupling is deliberate: a saved layout is
// portable across dataset re-uploads (as long as the column names still exist), exactly
// like a saved SQL query in useQueryHistory.
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

const state = reactive<DashboardState>({
  dashboards: loadArray<SavedDashboard>(SAVED_KEY),
})

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
// is sufficient: configs are plain data (strings/numbers/null), no functions or dates.
function cloneSnapshot(snapshot: DashboardSnapshot): DashboardSnapshot {
  return JSON.parse(JSON.stringify({ kpis: snapshot.kpis, charts: snapshot.charts }))
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
    kpis: copy.kpis,
    charts: copy.charts,
  }
  state.dashboards = [row, ...state.dashboards]
  persist(SAVED_KEY, state.dashboards)
  return row
}

// Return a fresh deep copy of a saved dashboard's configs (or null if the id is gone),
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
  persist(SAVED_KEY, state.dashboards)
}

function deleteDashboard(id: string): void {
  state.dashboards = state.dashboards.filter((d) => d.id !== id)
  persist(SAVED_KEY, state.dashboards)
}

export function useDashboards() {
  return { ...toRefs(state), saveDashboard, loadDashboard, renameDashboard, deleteDashboard }
}
