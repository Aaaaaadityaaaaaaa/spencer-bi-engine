import { reactive, toRefs } from 'vue'
import type { DashboardSnapshot, DashboardResponse } from '../types'
import { listDashboards, createDashboard, updateDashboard, deleteDashboard as apiDeleteDashboard } from '../services/api'

interface DashboardState {
  dashboards: DashboardResponse[]
  loading: boolean
  error: string | null
}

const state = reactive<DashboardState>({
  dashboards: [],
  loading: false,
  error: null
})

// Load dashboards from the server
export async function loadFromServer(): Promise<void> {
  state.loading = true
  state.error = null
  try {
    state.dashboards = await listDashboards()
  } catch (err: any) {
    state.error = err?.response?.data?.detail || err.message || 'Failed to load dashboards'
  } finally {
    state.loading = false
  }
}

function cloneSnapshot(snapshot: DashboardSnapshot): DashboardSnapshot {
  return JSON.parse(JSON.stringify({ pages: snapshot.pages, activePageId: snapshot.activePageId }))
}

// Now async
async function saveDashboard(sessionUuid: string, name: string, snapshot: DashboardSnapshot): Promise<DashboardResponse | null> {
  const clean = name.trim()
  if (!clean) return null
  const copy = cloneSnapshot(snapshot)
  const pagesJson = JSON.stringify(copy)
  
  try {
    const dash = await createDashboard(sessionUuid, clean, pagesJson)
    // Insert at front
    state.dashboards = [dash, ...state.dashboards]
    return dash
  } catch (err: any) {
    console.error("Failed to save dashboard:", err)
    return null
  }
}

function loadDashboard(id: number): DashboardSnapshot | null {
  const found = state.dashboards.find((d) => d.id === id)
  if (!found) return null
  try {
    return JSON.parse(found.pages_json)
  } catch {
    return null
  }
}

async function renameDashboard(id: number, name: string): Promise<void> {
  const clean = name.trim()
  if (!clean) return
  
  // Optimistic update
  const idx = state.dashboards.findIndex(d => d.id === id)
  if (idx !== -1) {
    state.dashboards[idx].name = clean
  }
  
  try {
    await updateDashboard(id, clean, undefined)
  } catch (err) {
    console.error("Failed to rename:", err)
    // Revert would go here in a robust app
  }
}

async function deleteDashboard(id: number): Promise<void> {
  state.dashboards = state.dashboards.filter((d) => d.id !== id)
  try {
    await apiDeleteDashboard(id)
  } catch (err) {
    console.error("Failed to delete:", err)
  }
}

export function useDashboards() {
  return { ...toRefs(state), saveDashboard, loadDashboard, renameDashboard, deleteDashboard, loadFromServer }
}

// Compatibility shim for useAuth.ts
export function loadForUser(userId: string | null): void {
  if (userId) {
    loadFromServer()
  } else {
    state.dashboards = []
  }
}
