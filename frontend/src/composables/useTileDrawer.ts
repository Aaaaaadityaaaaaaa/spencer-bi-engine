// Shared state for the per-visual settings drawer (Power BI–style). Lives outside any single
// view component so the drawer chrome can live at the app root while tiles (deep inside the
// Canvas) teleport their editor markup into it — keeping the teleport target out of the Canvas
// subtree avoids a Vue patcher crash when the target + source are patched in the same flush.
import { ref } from 'vue'
import type { ColumnMeta } from '../types'

export type SelectedTile = { kind: 'kpi' | 'chart'; id: number }

const selectedTile = ref<SelectedTile | null>(null)
const drawerColumns = ref<ColumnMeta[]>([])

export function useTileDrawer() {
  function openTileDrawer(kind: 'kpi' | 'chart', id: number, columns: ColumnMeta[]): void {
    drawerColumns.value = columns
    selectedTile.value = { kind, id }
  }
  function closeTileDrawer(): void {
    selectedTile.value = null
  }
  function isTileSelected(kind: 'kpi' | 'chart', id: number): boolean {
    return selectedTile.value?.kind === kind && selectedTile.value?.id === id
  }
  return { selectedTile, drawerColumns, openTileDrawer, closeTileDrawer, isTileSelected }
}
