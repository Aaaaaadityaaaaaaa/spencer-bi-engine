// The LIVE Canvas board, auto-persisted to localStorage (TASK-033, "persist immediately").
//
// This is deliberately NOT useDashboards: that store holds NAMED, explicitly-saved
// dashboards (a list the user manages). This holds exactly ONE board -- whatever the user
// is working on right now -- snapshotted on every tile edit so a reload restores it rather
// than throwing the work away. Named Save/Load slots remain useDashboards' job (TASK-035).
//
// Same idiom as useDashboards/useQueryHistory: per-user key namespacing via `k(base)`,
// tolerant read (never throws at import), swallow-on-quota write, JSON deep-clone. There is
// no reactive singleton here -- the board lives in ChartCanvas's refs; this module is just
// the read/write seam, called once at seed time and on every persist watch tick.
//
// The blob is MULTI-PAGE since TASK-034 (v2). A v1 blob (single page, no grid layout,
// written by TASK-033) is UPGRADED on read: its `{ kpis, charts }` is wrapped into one
// "Page 1" with a synthesized flow layout, so a board saved before the grid upgrade
// survives it. Writes are always v2.
import type {
  ActiveDashboardBlobV1,
  ActiveDashboardBlobV2,
  ActiveDashboardSnapshot,
  DashboardPage,
} from '../types'
import { generateFlowLayout } from '../utils/dashboardLayout'

const ACTIVE_KEY = 'spencer.activeDashboard'

// Per-user namespacing (TASK-027 parity): a shared browser must never leak one user's live
// board to another. useAuth sets the active user via loadForUser; with no user we no-op so
// a logged-out tab neither reads nor writes.
let currentUserId: string | null = null
function k(base: string): string {
  return currentUserId ? `${base}:${currentUserId}` : base
}

export function loadForUser(userId: string | null): void {
  currentUserId = userId
}

// A persisted page is trusted only if it has the full shape; a malformed one (hand-edited
// storage, a partial write) is dropped rather than crashing the Canvas. ChartCanvas further
// reconciles each surviving page's layout against its tiles, so a missing layout item is
// self-healing there — here we only guard the top-level shape.
function isValidPage(p: unknown): p is DashboardPage {
  if (!p || typeof p !== 'object') return false
  const r = p as Record<string, unknown>
  return (
    typeof r.id === 'string' &&
    typeof r.name === 'string' &&
    Array.isArray(r.kpis) &&
    Array.isArray(r.charts) &&
    Array.isArray(r.layout)
  )
}

// Wrap a pre-grid v1 snapshot into the multi-page v2 shape: one "Page 1" holding the same
// tiles, with a flow layout synthesized from their ids so the upgraded board looks freshly
// seeded (KPIs across the top, charts below) rather than piled at the origin.
function upgradeV1(sessionUuid: string, snap: ActiveDashboardSnapshot): ActiveDashboardBlobV2 {
  const layout = generateFlowLayout(
    snap.kpis.map((kpi) => kpi.id),
    snap.charts.map((c) => c.id),
  )
  const page: DashboardPage = {
    id: 'page-1',
    name: 'Page 1',
    kpis: snap.kpis,
    charts: snap.charts,
    layout,
  }
  return { v: 2, sessionUuid, pages: [page], activePageId: page.id }
}

// The restored board for the CURRENT user, or null if none/absent/corrupt/empty. Always
// returns the v2 shape (v1 blobs are upgraded in place). The caller (ChartCanvas) additionally
// checks `sessionUuid` matches before adopting it, so a board saved against a different dataset
// is ignored (seed fresh) rather than mis-rendered.
export function readActiveDashboard(): ActiveDashboardBlobV2 | null {
  if (typeof localStorage === 'undefined' || !currentUserId) return null
  try {
    const raw = localStorage.getItem(k(ACTIVE_KEY))
    if (!raw) return null
    const parsed = JSON.parse(raw) as Record<string, unknown>
    if (!parsed || typeof parsed.sessionUuid !== 'string') return null
    const sessionUuid = parsed.sessionUuid

    // v1 (TASK-033, pre-grid single page): upgrade to v2.
    if (parsed.v === 1) {
      const snap = (parsed as Partial<ActiveDashboardBlobV1>).snapshot
      if (!snap || !Array.isArray(snap.kpis) || !Array.isArray(snap.charts)) return null
      const upgraded = upgradeV1(sessionUuid, { kpis: snap.kpis, charts: snap.charts })
      // An empty v1 board upgrades to an empty page — treat as "nothing to restore".
      return upgraded.pages[0].kpis.length > 0 || upgraded.pages[0].charts.length > 0
        ? upgraded
        : null
    }

    // v2 (TASK-034, multi-page).
    if (parsed.v === 2) {
      const pagesRaw = parsed.pages
      if (!Array.isArray(pagesRaw)) return null
      const pages = pagesRaw.filter(isValidPage)
      if (pages.length === 0) return null
      // activePageId must point at a surviving page; else fall back to the first so a
      // corrupt/stale id can't leave the Canvas with no active page.
      const wanted = parsed.activePageId
      const activePageId =
        typeof wanted === 'string' && pages.some((p) => p.id === wanted) ? wanted : pages[0].id
      return { v: 2, sessionUuid, pages, activePageId }
    }

    return null
  } catch {
    return null
  }
}

// Snapshot the live board. Deep-cloned so the stored value is severed from the reactive
// Canvas arrays (a later edit must not silently mutate what's on disk). Quota/permission
// failures are non-fatal: the in-memory board still works; it just won't survive a reload.
export function persistActiveDashboard(
  sessionUuid: string,
  board: { pages: DashboardPage[]; activePageId: string },
): void {
  if (typeof localStorage === 'undefined' || !currentUserId) return
  try {
    const blob: ActiveDashboardBlobV2 = {
      v: 2,
      sessionUuid,
      pages: JSON.parse(JSON.stringify(board.pages)),
      activePageId: board.activePageId,
    }
    localStorage.setItem(k(ACTIVE_KEY), JSON.stringify(blob))
  } catch {
    // non-fatal (see above)
  }
}

export function clearActiveDashboard(): void {
  if (typeof localStorage === 'undefined' || !currentUserId) return
  try {
    localStorage.removeItem(k(ACTIVE_KEY))
  } catch {
    // non-fatal
  }
}
