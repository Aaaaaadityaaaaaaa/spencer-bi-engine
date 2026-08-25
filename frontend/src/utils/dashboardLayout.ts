// Shared grid geometry for the Power BI–style Canvas (TASK-034).
//
// KPI cards and chart tiles share ONE freeform grid (grid-layout-plus), so a tile's
// position/size is a `TileLayout { i, x, y, w, h }` where `i` is a COMPOSITE id
// ("kpi:<id>" / "chart:<id>") that keys back to the tile's numeric config id. These
// constants + helpers live here (not in ChartCanvas) because two places need them: the
// Canvas (grid props, seeding, add/remove) and useActiveDashboard (synthesizing a layout
// when upgrading a pre-grid v1 blob to the multi-page v2 shape).
import type { TileLayout } from '../types'

// Grid geometry. 12 columns is the Power BI / Bootstrap convention; rowHeight + margin are
// tuned so a KPI (h=3) is ~150px and a chart (h=8) is ~400px at the defaults below.
export const GRID_COLS = 12
export const GRID_ROW_HEIGHT = 40
export const GRID_MARGIN: [number, number] = [12, 12]

// Default tile sizes (grid units). Charts are wide + tall; KPIs are small squares.
export const KPI_W = 3
export const KPI_H = 3
export const CHART_W = 6
export const CHART_H = 8

// Minimum drag-resize sizes, so a tile can't be shrunk into an unreadable sliver.
export const KPI_MIN_W = 2
export const KPI_MIN_H = 2
export const CHART_MIN_W = 3
export const CHART_MIN_H = 4

// Composite tile ids: the grid needs a single unique `i` per item, but KPIs and charts
// have independent numeric id spaces, so the kind is prefixed. Parsing is the inverse.
export function kpiTileId(id: number): string {
  return `kpi:${id}`
}
export function chartTileId(id: number): string {
  return `chart:${id}`
}
export function parseTileId(i: string): { kind: 'kpi' | 'chart'; id: number } | null {
  const sep = i.indexOf(':')
  if (sep === -1) return null
  const kind = i.slice(0, sep)
  const id = Number(i.slice(sep + 1))
  if ((kind === 'kpi' || kind === 'chart') && Number.isInteger(id)) return { kind, id }
  return null
}

// Bottom edge (max y + h) of a layout — where the next appended tile starts, so a newly
// added KPI/chart lands below the existing ones rather than colliding at the origin.
export function layoutBottom(layout: TileLayout[]): number {
  return layout.reduce((m, it) => Math.max(m, it.y + it.h), 0)
}

// A left-to-right flow layout: KPIs first (small, 4 per row), charts after (large, 2 per
// row), each wrapping at GRID_COLS. Used to seed a fresh page and to synthesize a layout
// when upgrading a layout-less v1 blob (so an upgraded board looks freshly seeded).
export function generateFlowLayout(kpiIds: number[], chartIds: number[]): TileLayout[] {
  const out: TileLayout[] = []
  let x = 0
  let y = 0
  for (const id of kpiIds) {
    if (x + KPI_W > GRID_COLS) {
      x = 0
      y += KPI_H
    }
    out.push({ i: kpiTileId(id), x, y, w: KPI_W, h: KPI_H })
    x += KPI_W
  }
  // Start charts on a fresh row so a half-filled KPI row doesn't wedge a wide chart beside it.
  if (x !== 0) {
    x = 0
    y += KPI_H
  }
  for (const id of chartIds) {
    if (x + CHART_W > GRID_COLS) {
      x = 0
      y += CHART_H
    }
    out.push({ i: chartTileId(id), x, y, w: CHART_W, h: CHART_H })
    x += CHART_W
  }
  return out
}
