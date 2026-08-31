<script setup lang="ts">
import { ref, computed, watch, onActivated, nextTick } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import {
  Loader2, MoreVertical, Download, Eye, BarChart3, ChevronDown,
  ArrowUp, ArrowDown, Pin, Search, X, RotateCcw, Plus, Copy,
  Rows3, Rows4,
} from '@lucide/vue'
import { useSession } from '../composables/useSession'
import { fetchData, exportTable, apiErrorMessage, blobErrorMessage } from '../services/api'
import type { ExportFormat } from '../services/api'
import { downloadBlob, exportFilename, copyToClipboard } from '../utils/csvExport'
import { friendlyTableName } from '../utils/tableName'
import { useToasts } from '../composables/useToast'
import type { DataColumn, OpKind, OpRequest, SortSpec } from '../types'

// Window size for one fetch: matches the backend's default `limit` and is the
// infinite-scroll page size (the backend clamps anything above 1000).
const PAGE = 500
const ROW_H_COMFY = 36   // px; comfortable default row height
const ROW_H_COMPACT = 26 // px; compact density for tight scans of wide tables
const COL_W = 160  // px; fixed column width -> header/body columns stay aligned

// Per-user row density (Batch 3 / Table). Persists in localStorage so the choice
// survives reloads. 'compact' shows ~30% more rows per screen; 'comfy' (default)
// is the readable baseline.
type Density = 'compact' | 'comfy'
const DENSITY_KEY = 'spencer.grid.density'
function loadDensity(): Density {
  try {
    const v = localStorage.getItem(DENSITY_KEY)
    return v === 'compact' ? 'compact' : 'comfy'
  } catch {
    return 'comfy'
  }
}
const density = ref<Density>(loadDensity())
const ROW_H = computed(() => (density.value === 'compact' ? ROW_H_COMPACT : ROW_H_COMFY))
watch(density, (v) => { try { localStorage.setItem(DENSITY_KEY, v) } catch { /* storage may be disabled */ } })

// Numeric column types are right-aligned with tabular-nums so amounts and quantities
// line up vertically (much easier to scan, much harder to mis-read). Includes the
// integer/float family DuckDB reports plus dates — dates are right-aligned so time
// series look right.
const NUMERIC_TYPES = new Set(['BIGINT', 'INTEGER', 'SMALLINT', 'TINYINT', 'HUGEINT', 'DOUBLE', 'FLOAT', 'REAL', 'DECIMAL', 'NUMERIC', 'DATE', 'TIMESTAMP'])
function isNumericType(t: string | undefined): boolean {
  return !!t && NUMERIC_TYPES.has(t.toUpperCase())
}

const { sessionUuid, tableName, fileName, dataVersion, tables, uploading, error, setActiveTable, addTable, updateCell } = useSession()

// Multi-table switcher (TASK-039): a hidden file input backs the "Add table" button;
// addError surfaces an add failure (e.g. a duplicate table name) inline in the toolbar,
// since the session error banner only renders on the empty upload screen.
const tableFileInput = ref<HTMLInputElement | null>(null)
const addError = ref<string | null>(null)
async function onAddTableFile(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // let the user re-pick the same file after an error
  if (!file) return
  addError.value = null
  const ok = await addTable(file)
  if (!ok) addError.value = error.value ?? 'Could not add table.'
}

// Per-column ⋮ header menu -> asks the parent (TableView) to open the op dialog
// pre-scoped to this column. The ribbon covers the same ops without a preset column.
const emit = defineEmits<{
  'column-op': [req: OpRequest]
  'profile-column': [column: string]
}>()

const COLUMN_OPS: { op: OpKind; label: string }[] = [
  { op: 'drop_null', label: 'Drop rows with nulls' },
  { op: 'impute_null', label: 'Fill nulls…' },
  { op: 'fill_down', label: 'Fill down / up…' },
  { op: 'cast', label: 'Change type…' },
  { op: 'rename_column', label: 'Rename…' },
  { op: 'string_normalize', label: 'Normalize text…' },
  { op: 'split_column', label: 'Split / extract…' },
  { op: 'date_extract', label: 'Date parts…' },
  { op: 'bin_column', label: 'Bin into ranges…' },
  { op: 'flag_outliers', label: 'Flag outliers…' },
  { op: 'drop_column', label: 'Drop column' },
]

// Which column's menu is open, and where to anchor it. The menu is position:fixed
// (computed from the button rect) so the grid's overflow-auto can't clip it.
// TASK-042: the anchor also carries a dynamic max-height and an up/down flag so the menu
// is capped to the space actually available from the button (not a flat 70vh measured from
// the viewport top, which let a low button's menu run off the bottom edge WITHOUT ever
// triggering its own scrollbar). It flips upward when there's more room above.
const menuCol = ref<string | null>(null)
const menuPos = ref<{ x: number; y: number; maxH: number; up: boolean }>({ x: 0, y: 0, maxH: 320, up: false })

function toggleMenu(col: string, e: MouseEvent): void {
  if (menuCol.value === col) {
    menuCol.value = null
    return
  }
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  const margin = 8 // keep the menu clear of the very screen edge
  const gap = 4 // small offset between the button and the menu
  const spaceBelow = window.innerHeight - r.bottom - margin
  const spaceAbove = r.top - margin
  // Open upward only when the menu won't reasonably fit below AND there's more room above.
  const up = spaceBelow < 220 && spaceAbove > spaceBelow
  const maxH = Math.max(160, (up ? spaceAbove : spaceBelow) - gap)
  menuPos.value = {
    x: r.right,
    // `y` is the CSS offset for the chosen edge: for a downward menu it's the top
    // (button bottom + gap); for an upward one it's the bottom, measured from the
    // viewport bottom up to just above the button's top.
    y: up ? window.innerHeight - r.top + gap : r.bottom + gap,
    maxH,
    up,
  }
  menuCol.value = col
}

// Inline style for the column ⋮ menu: pin to top OR bottom depending on the flip, cap the
// height to the measured space (so overflow-y-auto actually scrolls), and keep the
// right-aligned translate. Kept as a computed for readability over an inline expression.
const menuStyle = computed<Record<string, string>>(() => {
  const p = menuPos.value
  return {
    [p.up ? 'bottom' : 'top']: p.y + 'px',
    left: p.x + 'px',
    maxHeight: p.maxH + 'px',
    transform: 'translateX(-100%)',
  }
})

function chooseOp(op: OpKind): void {
  const col = menuCol.value
  menuCol.value = null
  if (col) emit('column-op', { op, column: col })
}

// Profiling is a read-only inspection, not a transform, so it emits its own event
// (the parent opens the profile drawer) rather than routing through the op dialog.
function chooseProfile(): void {
  const col = menuCol.value
  menuCol.value = null
  if (col) emit('profile-column', col)
}

// #Batch12: copy a column's values to the clipboard from the header ⋮ menu — a fast way
// to reuse a column elsewhere (paste into the SQL editor, a sheet, a prompt). Copies the
// currently-loaded rows (the visible window), one value per line; the toast states exactly
// how many so nothing is silently truncated on a paginated table. Uses the shared, never-
// throwing clipboard helper.
const { pushToast } = useToasts()
async function copyColumn(): Promise<void> {
  const col = menuCol.value
  menuCol.value = null
  if (!col) return
  const vals = rows.value.map((r) => cell(r, col))
  const ok = await copyToClipboard(vals.join('\n'))
  if (ok) pushToast(`Copied ${vals.length} values from "${col}"`, 'success')
  else pushToast('Could not copy — select and copy manually', 'error')
}

const rows = ref<Record<string, unknown>[]>([])
const columns = ref<DataColumn[]>([])
const total = ref(0)
const loading = ref(false)
const gridError = ref<string | null>(null)
const scrollEl = ref<HTMLDivElement | null>(null)

// #5 in-cell edit: a parallel array of the stable DuckDB rowid for each loaded row,
// filled from /data in lockstep with `rows` (same order, same offset/concat), so
// rowids[i] addresses rows[i]. It's the anchor the update_cell transform uses to hit
// exactly one cell. `editing` tracks which cell (by row index + column) is open, and
// `editValue` is the text box's working value.
const rowids = ref<number[]>([])
const editing = ref<{ index: number; col: string } | null>(null)
const editValue = ref('')
const editInput = ref<HTMLInputElement | HTMLInputElement[] | null>(null)

function isEditing(index: number, col: string): boolean {
  return editing.value?.index === index && editing.value?.col === col
}
function focusEditInput(): void {
  void nextTick(() => {
    const el = editInput.value
    const input = Array.isArray(el) ? el[0] : el
    input?.focus()
    input?.select()
  })
}
function startEdit(index: number, col: string): void {
  // Need a stable rowid to address the cell; if the window didn't carry one, skip.
  if (rowids.value[index] === undefined) return
  const raw = rows.value[index]?.[col]
  editValue.value = raw === null || raw === undefined ? '' : String(raw)
  editing.value = { index, col }
  focusEditInput()
}
function cancelEdit(): void {
  editing.value = null
  editValue.value = ''
}
async function commitEdit(): Promise<void> {
  const target = editing.value
  if (!target) return
  const { index, col } = target
  editing.value = null // close the editor immediately (optimistic)
  const rid = rowids.value[index]
  const row = rows.value[index]
  if (rid === undefined || !row) return
  const prev = row[col]
  // Empty box clears the cell to NULL; otherwise send the raw text (the backend CASTs
  // it to the column's own type and fails closed if it can't parse).
  const text = editValue.value
  const value: unknown = text === '' ? null : text
  const display = text === '' ? null : text
  // No-op guard: nothing to persist if the value is unchanged.
  const prevText = prev === null || prev === undefined ? '' : String(prev)
  if (text === prevText) return
  // Optimistic patch so the edit shows instantly (no full reload). Replace the row
  // object so the virtualized cell re-renders.
  rows.value[index] = { ...row, [col]: display }
  const ok = await updateCell(col, rid, value)
  if (!ok) {
    // Roll back and surface the reason (e.g. value can't cast to the column type).
    rows.value[index] = { ...rows.value[index], [col]: prev }
    gridError.value = error.value ?? 'Could not update the cell.'
  }
}

// Generation token: every full reset (session switch, transform, sort/search
// change) bumps this. A window fetch captures the token at launch and discards
// its result if the token moved on, so a stale in-flight fetch can never write
// another view's rows (e.g. old sort order) after a newer reload started.
const reqGen = ref(0)

const rowVirtualizer = useVirtualizer<HTMLDivElement, HTMLDivElement>(
  computed(() => ({
    count: rows.value.length,
    getScrollElement: () => scrollEl.value,
    estimateSize: () => ROW_H.value,
    // Overscan buffers rows above/below the viewport. It has to be generous here
    // because the browser scrolls this container on the COMPOSITOR thread and
    // delivers 'scroll' events to the main thread late/batched: during a fast fling
    // the compositor shifts the already-painted layer before the virtualizer can
    // re-render, so a small band gets outrun and the viewport paints blank until the
    // main thread catches up. 24 rows (~860px) each side covers a hard fling without
    // bloating the render -- each row is 5 short cells, so ~50-60 rendered rows stay
    // cheap. (At-rest correctness is unaffected; this only widens the in-motion band.)
    overscan: 24,
  })),
)
const virtualRows = computed(() => rowVirtualizer.value.getVirtualItems())
const totalSize = computed(() => rowVirtualizer.value.getTotalSize())

// <keep-alive> (App.vue) detaches this view's DOM on navigation and re-attaches it on
// return. The virtualizer's ResizeObserver / scroll listener persist across that, so its
// container rect stays valid -- but nothing fires the recompute that reactivation needs,
// leaving the last (empty) visible range on screen until the user nudges the scrollbar.
// Forcing a re-measure on reactivation runs that recompute so the rows paint immediately.
onActivated(() => {
  void nextTick(() => rowVirtualizer.value.measure())
})

// --- In-grid view controls (TASK-022) --------------------------------------
// All four are view-only: they change what/how the grid renders (or which server
// window it asks for), never the underlying table. Cleaning ops and export always
// act on the FULL, unordered column set, so none of this can drop data or desync
// a transform.

// Column show/hide: the set of hidden column names.
const hiddenCols = ref<Set<string>>(new Set())
// Column order (all columns, incl. hidden, by name). Drag-reorder rewrites this;
// hiding a column keeps its slot so unhiding restores its place.
const colOrder = ref<string[]>([])
// Frozen (pinned) columns render sticky-left, ahead of the scrolling columns.
const pinnedCols = ref<Set<string>>(new Set())
// Columns drawn with a value->colour heatmap (numeric only; needs `ranges`).
const heatmapCols = ref<Set<string>>(new Set())
// Whole-table [min,max] per numeric column, from the first window (offset 0).
const ranges = ref<Record<string, [number, number]>>({})
// Server-side multi-sort spec, in priority order. Sent to /data as "col:dir,...".
const sortSpec = ref<SortSpec[]>([])
// Raw search box text; debounced into `search` (the value actually sent as `q`).
const searchInput = ref('')
const search = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null

// Columns in render order: pinned first (each sticky at a cumulative left offset),
// then the rest, both following colOrder minus hidden.
const orderedVisible = computed<DataColumn[]>(() => {
  const byName = new Map(columns.value.map((c) => [c.name, c]))
  const out: DataColumn[] = []
  for (const n of colOrder.value) {
    const c = byName.get(n)
    if (c && !hiddenCols.value.has(n)) out.push(c)
  }
  return out
})
interface ColMeta { col: DataColumn; pinned: boolean; left: number }
const displayCols = computed<ColMeta[]>(() => {
  const pins: DataColumn[] = []
  const rest: DataColumn[] = []
  for (const c of orderedVisible.value) {
    if (pinnedCols.value.has(c.name)) pins.push(c)
    else rest.push(c)
  }
  const out: ColMeta[] = []
  pins.forEach((col, i) => out.push({ col, pinned: true, left: i * COL_W }))
  rest.forEach((col) => out.push({ col, pinned: false, left: 0 }))
  return out
})
const gridWidth = computed(() => displayCols.value.length * COL_W)

const colMenuOpen = ref(false)
const colMenuPos = ref<{ x: number; y: number }>({ x: 0, y: 0 })

function toggleColMenu(e: MouseEvent): void {
  if (colMenuOpen.value) {
    colMenuOpen.value = false
    return
  }
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  colMenuPos.value = { x: r.right, y: r.bottom }
  colMenuOpen.value = true
}
function toggleColVisible(name: string): void {
  const next = new Set(hiddenCols.value)
  if (next.has(name)) next.delete(name)
  else next.add(name)
  hiddenCols.value = next // reassign (not mutate) so the computed re-runs
}
function showAllCols(): void {
  hiddenCols.value = new Set()
}

// --- sort: click a header to cycle asc -> desc -> off; shift-click for multi ---
function sortInfo(name: string): { dir: 'asc' | 'desc'; idx: number } | null {
  const i = sortSpec.value.findIndex((s) => s.column === name)
  return i < 0 ? null : { dir: sortSpec.value[i].dir, idx: i + 1 }
}
function onHeaderClick(col: DataColumn, e: MouseEvent): void {
  const name = col.name
  const cur = sortSpec.value
  const i = cur.findIndex((s) => s.column === name)
  let next: SortSpec[]
  if (e.shiftKey) {
    // Additive: extend/advance/remove just this key, keeping the others' order.
    next = [...cur]
    if (i < 0) next.push({ column: name, dir: 'asc' })
    else if (cur[i].dir === 'asc') next[i] = { column: name, dir: 'desc' }
    else next.splice(i, 1)
  } else {
    // Single key: cycle this column, dropping any other sort.
    if (i < 0) next = [{ column: name, dir: 'asc' }]
    else if (cur[i].dir === 'asc') next = [{ column: name, dir: 'desc' }]
    else next = []
  }
  sortSpec.value = next
  reloadFromTop()
}

// --- drag to reorder columns (view-only; rewrites colOrder by name) ---------
const dragCol = ref<string | null>(null)
const dragOverCol = ref<string | null>(null)
function onDragStart(name: string, e: DragEvent): void {
  dragCol.value = name
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    try { e.dataTransfer.setData('text/plain', name) } catch { /* some browsers restrict */ }
  }
}
function onDragOver(name: string): void {
  if (dragCol.value && dragCol.value !== name) dragOverCol.value = name
}
function onDrop(target: string): void {
  const src = dragCol.value
  dragCol.value = null
  dragOverCol.value = null
  if (!src || src === target) return
  const arr = [...colOrder.value]
  const from = arr.indexOf(src)
  const to = arr.indexOf(target)
  if (from < 0 || to < 0) return
  arr.splice(from, 1)
  arr.splice(to, 0, src)
  colOrder.value = arr
}
function onDragEnd(): void {
  dragCol.value = null
  dragOverCol.value = null
}

// --- pin / heatmap / hide, driven from the per-column ⋮ menu ----------------
const canHeatmap = computed(() => !!(menuCol.value && ranges.value[menuCol.value]))
const menuPinned = computed(() => !!(menuCol.value && pinnedCols.value.has(menuCol.value)))
const menuHeat = computed(() => !!(menuCol.value && heatmapCols.value.has(menuCol.value)))

function togglePin(): void {
  const c = menuCol.value
  menuCol.value = null
  if (!c) return
  const n = new Set(pinnedCols.value)
  if (n.has(c)) n.delete(c)
  else n.add(c)
  pinnedCols.value = n
}
function toggleHeatmap(): void {
  const c = menuCol.value
  menuCol.value = null
  if (!c) return
  const n = new Set(heatmapCols.value)
  if (n.has(c)) n.delete(c)
  else n.add(c)
  heatmapCols.value = n
}
function hideFromMenu(): void {
  const c = menuCol.value
  menuCol.value = null
  if (!c) return
  const n = new Set(hiddenCols.value)
  n.add(c)
  hiddenCols.value = n
}

// --- heatmap colour: opaque light->strong blue by the value's position in
// [min,max]. Opaque (not alpha) so a pinned + heat cell never bleeds the
// scrolling content behind it; text flips to white on the darker high end.
function heatBg(t: number): string {
  const c0 = [239, 246, 255] // blue-50
  const c1 = [37, 99, 235] // blue-600
  const r = Math.round(c0[0] + (c1[0] - c0[0]) * t)
  const g = Math.round(c0[1] + (c1[1] - c0[1]) * t)
  const b = Math.round(c0[2] + (c1[2] - c0[2]) * t)
  return `rgb(${r}, ${g}, ${b})`
}
function heatStyle(name: string, value: unknown): { backgroundColor: string; color?: string } | null {
  if (!heatmapCols.value.has(name)) return null
  const r = ranges.value[name]
  if (!r) return null
  if (value === null || value === undefined) return null
  const num = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(num)) return null
  const [lo, hi] = r
  const t = hi > lo ? Math.min(1, Math.max(0, (num - lo) / (hi - lo))) : 0.5
  const st: { backgroundColor: string; color?: string } = { backgroundColor: heatBg(t) }
  if (t > 0.62) st.color = '#ffffff'
  return st
}

function headerCellStyle(meta: ColMeta): Record<string, string> {
  const s: Record<string, string> = { width: COL_W + 'px' }
  if (meta.pinned) {
    s.position = 'sticky'
    s.left = meta.left + 'px'
  }
  return s
}
function bodyCellStyle(meta: ColMeta, row: Record<string, unknown> | undefined): Record<string, string> {
  const s: Record<string, string> = { width: COL_W + 'px' }
  if (meta.pinned) {
    s.position = 'sticky'
    s.left = meta.left + 'px'
  }
  const h = heatStyle(meta.col.name, row ? row[meta.col.name] : undefined)
  if (h) {
    s.backgroundColor = h.backgroundColor
    if (h.color) s.color = h.color
  }
  return s
}

// Any non-default view state -> show the "Reset view" affordance.
const viewDirty = computed(
  () =>
    sortSpec.value.length > 0 ||
    pinnedCols.value.size > 0 ||
    heatmapCols.value.size > 0 ||
    !!search.value ||
    hiddenCols.value.size > 0,
)
function resetView(): void {
  // Capture the server-affecting state BEFORE clearing it: a reload is only
  // needed if a sort or search was actually active (pin/heatmap/order/hide are
  // client-only and never touch the window).
  const hadSort = sortSpec.value.length > 0
  const hadSearch = !!search.value
  sortSpec.value = []
  pinnedCols.value = new Set()
  heatmapCols.value = new Set()
  hiddenCols.value = new Set()
  colOrder.value = columns.value.map((c) => c.name)
  if (searchTimer) { clearTimeout(searchTimer); searchTimer = null }
  searchInput.value = ''
  search.value = ''
  if (!hadSort && !hadSearch) return
  reloadFromTop()
}

// Debounce the search box: only the settled value hits the server, and it resets
// the window to the top (offset 0) so results start from the first match.
watch(searchInput, (v) => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    const next = v.trim()
    if (next === search.value) return
    search.value = next
    reloadFromTop()
  }, 300)
})
function clearSearch(): void {
  if (searchTimer) { clearTimeout(searchTimer); searchTimer = null }
  searchInput.value = ''
  if (!search.value) return
  search.value = ''
  reloadFromTop()
}

async function loadWindow(offset: number): Promise<void> {
  const uuid = sessionUuid.value
  const gen = reqGen.value
  if (!uuid || loading.value) return
  if (offset > 0 && rows.value.length >= total.value) return // fully loaded
  loading.value = true
  gridError.value = null
  try {
    const res = await fetchData(uuid, {
      offset,
      limit: PAGE,
      tableName: tableName.value ?? undefined,
      sort: sortSpec.value,
      search: search.value,
    })
    // Session switched (new upload) OR a newer reset superseded this fetch while it
    // was in flight -> drop the stale window rather than writing the wrong rows.
    if (uuid !== sessionUuid.value || gen !== reqGen.value) return
    if (offset === 0) {
      columns.value = res.columns
      rows.value = res.rows
      rowids.value = res.rowids ?? []
      // Heatmap scale: whole-table ranges arrive only on the first window; cache
      // them (left unfiltered server-side so the scale stays stable under search).
      ranges.value = res.ranges ?? {}
      // Seed/extend the column order: keep the current order for surviving columns,
      // append any newly-added ones, drop any that disappeared (rename/drop).
      const names = res.columns.map((c) => c.name)
      const kept = colOrder.value.filter((n) => names.includes(n))
      const added = names.filter((n) => !kept.includes(n))
      colOrder.value = [...kept, ...added]
    } else {
      rows.value = rows.value.concat(res.rows)
      rowids.value = rowids.value.concat(res.rowids ?? [])
    }
    total.value = res.total
  } catch (e) {
    if (uuid === sessionUuid.value && gen === reqGen.value) gridError.value = apiErrorMessage(e)
  } finally {
    if (uuid === sessionUuid.value && gen === reqGen.value) loading.value = false
  }
}

// Single reload entry point: bump the generation (discarding any in-flight
// window), clear the loaded prefix, scroll to top, and fetch the first window
// under the current sort/search.
function reloadFromTop(): void {
  if (!sessionUuid.value) return
  reqGen.value++
  rows.value = []
  rowids.value = []
  cancelEdit()
  total.value = 0
  gridError.value = null
  loading.value = false
  if (scrollEl.value) scrollEl.value.scrollTop = 0
  void loadWindow(0)
}

// Export the ENTIRE cleaned table to `fmt`, server-side: the backend streams the whole
// table (DuckDB COPY for csv/tsv/json/parquet, openpyxl for xlsx) so we don't page it
// client-side. It always reflects the current cleaned state (same session table the grid
// reads) -- NOT the current sort/search view, which are grid-local. Aborts cleanly if the
// session switches mid-export.
const exporting = ref(false)
const exportMenuOpen = ref(false)
const exportMenuPos = ref<{ x: number; y: number }>({ x: 0, y: 0 })

const EXPORT_FORMATS: { fmt: ExportFormat; label: string; ext: string }[] = [
  { fmt: 'csv', label: 'CSV (.csv)', ext: 'csv' },
  { fmt: 'xlsx', label: 'Excel (.xlsx)', ext: 'xlsx' },
  { fmt: 'parquet', label: 'Parquet (.parquet)', ext: 'parquet' },
  { fmt: 'json', label: 'JSON (.json)', ext: 'json' },
]

function toggleExportMenu(e: MouseEvent): void {
  if (exportMenuOpen.value) {
    exportMenuOpen.value = false
    return
  }
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  exportMenuPos.value = { x: r.right, y: r.bottom }
  exportMenuOpen.value = true
}

async function exportAs(fmt: ExportFormat, ext: string): Promise<void> {
  const uuid = sessionUuid.value
  exportMenuOpen.value = false
  if (!uuid || exporting.value || columns.value.length === 0) return
  exporting.value = true
  gridError.value = null
  try {
    const blob = await exportTable(uuid, fmt, tableName.value ?? undefined)
    if (uuid !== sessionUuid.value) return // session switched -> discard the download
    downloadBlob(exportFilename(fileName.value, '-cleaned', ext), blob)
  } catch (e) {
    // A failed blob request carries its error body as a Blob, not parsed JSON.
    if (uuid === sessionUuid.value) gridError.value = await blobErrorMessage(e)
  } finally {
    // Always release the flag -- it is UI-only, so a stale-session write is harmless
    // and never clearing it would lock exports for the next session.
    exporting.value = false
  }
}

// A new (or cleared) session resets the grid AND every view control, then loads
// the first window.
watch(
  sessionUuid,
  (uuid) => {
    rows.value = []
    rowids.value = []
    cancelEdit()
    columns.value = []
    total.value = 0
    gridError.value = null
    menuCol.value = null
    // A different dataset -> forget every per-dataset view choice.
    hiddenCols.value = new Set()
    colOrder.value = []
    pinnedCols.value = new Set()
    heatmapCols.value = new Set()
    ranges.value = {}
    sortSpec.value = []
    if (searchTimer) { clearTimeout(searchTimer); searchTimer = null }
    searchInput.value = ''
    search.value = ''
    dragCol.value = null
    dragOverCol.value = null
    colMenuOpen.value = false
    exportMenuOpen.value = false
    if (uuid) reloadFromTop()
  },
  { immediate: true },
)

// A transform / undo / redo bumps dataVersion, and switching the active table changes
// tableName — both mean the grid must reload a clean first window. Sort + search feed the
// server window and could reference a column absent from the new schema/table, so both
// are cleared (fail-safe against a 400); pin/heatmap/order are client-only and degrade
// gracefully (an absent column is simply filtered out), so they persist.
function resetToCleanWindow(): void {
  if (!sessionUuid.value) return
  menuCol.value = null
  colMenuOpen.value = false
  exportMenuOpen.value = false
  sortSpec.value = []
  if (searchTimer) { clearTimeout(searchTimer); searchTimer = null }
  searchInput.value = ''
  search.value = ''
  reloadFromTop()
}
watch(dataVersion, resetToCleanWindow)
// Active-table switch (same session): reload the grid onto the newly selected table.
// Guarded so the initial null→table set on upload/restore doesn't double-fetch — the
// sessionUuid watch above already loads the first table in that case.
watch(tableName, (next, prev) => {
  if (next && prev && next !== prev) resetToCleanWindow()
})

// Infinite scroll: when the last rendered row reaches the tail of what we have,
// fetch the next window. `loading` is set synchronously in loadWindow, so this
// can fire repeatedly during a scroll without launching overlapping requests.
watch(virtualRows, (items) => {
  const last = items[items.length - 1]
  if (!last) return
  if (last.index >= rows.value.length - 1 && rows.value.length < total.value) {
    void loadWindow(rows.value.length)
  }
})

// Display coercion only. NULL -> blank cell; objects -> JSON. Type-aware
// formatting (dates, number alignment, muted nulls) is deferred to TASK-007.
function cell(row: Record<string, unknown> | undefined, name: string): string {
  if (!row) return ''
  const v = row[name]
  if (v === null || v === undefined) return ''
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}
</script>

<template>
  <div class="flex flex-col overflow-hidden rounded-5 border border-outline-gray-1 bg-surface-base shadow-sm">
    <div class="flex items-center justify-between border-b border-outline-gray-1 bg-surface-gray-1 px-4 py-3">
      <div class="flex items-center gap-2">
        <h3 class="text-sm font-semibold text-ink-gray-8">Data Grid</h3>
        <!-- Multi-table switcher (TASK-039): pick which loaded table the grid + data-prep act on. -->
        <select
          v-if="sessionUuid && tables.length > 1"
          :value="tableName ?? ''"
          class="rounded-2 border border-outline-gray-2 bg-surface-base py-1 pl-2 pr-6 text-xs font-medium text-ink-gray-8 focus:border-primary focus:outline-none"
          title="Switch the active table"
          @change="setActiveTable(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="t in tables" :key="t.table_name" :value="t.table_name">
            {{ friendlyTableName(t.table_name) }}{{ t.is_primary ? ' (primary)' : '' }}
          </option>
        </select>
        <!-- Add another table to this session (secondary; the switcher then lists it). -->
        <button
          v-if="sessionUuid"
          type="button"
          class="inline-flex items-center gap-1 rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-1 text-xs font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2 disabled:cursor-not-allowed disabled:opacity-50"
          title="Add another table to this session"
          :disabled="uploading"
          @click="tableFileInput?.click()"
        >
          <Loader2 v-if="uploading" class="h-3.5 w-3.5 animate-spin text-primary" />
          <Plus v-else class="h-3.5 w-3.5" />
          Add table
        </button>
        <input
          ref="tableFileInput"
          type="file"
          accept=".csv,.tsv,.parquet,.json,.xlsx"
          class="hidden"
          @change="onAddTableFile"
        />
        <span v-if="addError" class="max-w-[16rem] truncate text-xs text-ink-red" :title="addError">{{ addError }}</span>
      </div>
      <div class="flex items-center gap-3">
        <span class="text-xs text-ink-gray-5">
          <template v-if="sessionUuid">
            {{ rows.length.toLocaleString() }} / {{ total.toLocaleString() }} rows
            <span v-if="search" class="text-ink-gray-4">(filtered)</span>
            <span v-if="loading" class="inline-flex items-center gap-1 text-primary">
              <Loader2 class="h-3 w-3 animate-spin" /> loading…
            </span>
          </template>
          <template v-else>0 rows</template>
        </span>

        <!-- Search all columns (server-side substring, debounced) -->
        <div v-if="sessionUuid" class="relative">
          <Search class="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-gray-4" />
          <input
            v-model="searchInput"
            type="text"
            placeholder="Search all columns…"
            class="w-48 rounded-2 border border-outline-gray-2 bg-surface-base py-1 pl-7 pr-6 text-xs text-ink-gray-8 placeholder:text-ink-gray-4 focus:border-primary focus:outline-none"
          />
          <button
            v-if="searchInput"
            type="button"
            class="absolute right-1.5 top-1/2 -translate-y-1/2 text-ink-gray-4 transition-colors hover:text-ink-gray-7"
            title="Clear search"
            @click="clearSearch"
          >
            <X class="h-3.5 w-3.5" />
          </button>
        </div>

        <button
          v-if="sessionUuid && viewDirty"
          type="button"
          class="inline-flex items-center gap-1 rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-1 text-xs font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
          title="Clear sort, filter, pins, heatmap, hidden & reordered columns"
          @click.stop="resetView"
        >
          <RotateCcw class="h-3.5 w-3.5" /> Reset view
        </button>
        <!-- Row density (Batch 3 / Table). Two visual modes that re-flow the whole grid
             instantly; persists across reloads. -->
        <div
          v-if="sessionUuid"
          class="inline-flex overflow-hidden rounded-2 border border-outline-gray-2"
          role="group"
          aria-label="Row density"
          title="Row density"
        >
          <button
            type="button"
            class="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium transition-colors"
            :class="density === 'compact'
              ? 'bg-surface-gray-2 text-ink-gray-9'
              : 'bg-surface-base text-ink-gray-5 hover:text-ink-gray-8'"
            :aria-pressed="density === 'compact'"
            title="Compact rows"
            @click.stop="density = 'compact'"
          >
            <Rows3 class="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1 border-l border-outline-gray-2 px-2 py-1 text-xs font-medium transition-colors"
            :class="density === 'comfy'
              ? 'bg-surface-gray-2 text-ink-gray-9'
              : 'bg-surface-base text-ink-gray-5 hover:text-ink-gray-8'"
            :aria-pressed="density === 'comfy'"
            title="Comfortable rows"
            @click.stop="density = 'comfy'"
          >
            <Rows4 class="h-3.5 w-3.5" />
          </button>
        </div>
        <button
          v-if="sessionUuid"
          type="button"
          class="inline-flex items-center gap-1 rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-1 text-xs font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
          :class="{ 'bg-surface-gray-2': colMenuOpen }"
          title="Show or hide columns"
          @click.stop="toggleColMenu($event)"
        >
          <Eye class="h-3.5 w-3.5" /> Columns
        </button>
        <button
          v-if="sessionUuid"
          type="button"
          class="inline-flex items-center gap-1 rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-1 text-xs font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2 disabled:cursor-not-allowed disabled:opacity-50"
          :class="{ 'bg-surface-gray-2': exportMenuOpen }"
          :disabled="exporting || total === 0"
          title="Download the full cleaned table"
          @click.stop="toggleExportMenu($event)"
        >
          <Loader2 v-if="exporting" class="h-3.5 w-3.5 animate-spin text-primary" />
          <Download v-else class="h-3.5 w-3.5" />
          Export
          <ChevronDown class="h-3 w-3" />
        </button>
      </div>
    </div>

    <!-- Scroll container is always mounted so the virtualizer can attach to it
         before any data arrives; the states below render inside it. -->
    <div ref="scrollEl" class="overflow-auto relative" style="height: 440px" @scroll="menuCol = null; colMenuOpen = false; exportMenuOpen = false">
      <div
        v-if="gridError"
        class="absolute inset-0 flex items-center justify-center px-4 text-center text-sm text-ink-red"
      >
        {{ gridError }}
      </div>
      <div
        v-else-if="!sessionUuid"
        class="absolute inset-0 flex items-center justify-center text-sm text-ink-gray-4"
      >
        Upload data to view grid
      </div>
      <div
        v-else-if="loading && rows.length === 0"
        class="absolute inset-0 flex items-center justify-center gap-2 text-sm text-ink-gray-4"
      >
        <Loader2 class="h-4 w-4 animate-spin" /> Loading…
      </div>
      <div
        v-else-if="!loading && rows.length === 0 && search"
        class="absolute inset-0 flex items-center justify-center px-4 text-center text-sm text-ink-gray-4"
      >
        No rows match “{{ search }}”.
      </div>

      <div v-else :style="{ width: gridWidth + 'px', minWidth: '100%' }">
        <!-- Sticky header row (pins vertically; scrolls horizontally with body).
             Each header: click to sort (shift-click to add a secondary key),
             drag to reorder. -->
        <div class="flex sticky top-0 z-10 border-b border-outline-gray-1 bg-surface-gray-1">
          <div
            v-for="meta in displayCols"
            :key="meta.col.name"
            class="flex shrink-0 cursor-pointer select-none items-center gap-1 px-3 py-2 transition-colors hover:bg-surface-gray-2"
            :class="[
              meta.pinned ? 'z-[5] bg-surface-gray-1' : '',
              dragOverCol === meta.col.name ? 'ring-2 ring-inset ring-primary' : '',
              dragCol === meta.col.name ? 'opacity-50' : '',
              isNumericType(meta.col.type) ? 'justify-end' : '',
            ]"
            :style="headerCellStyle(meta)"
            draggable="true"
            :title="meta.col.name + ' · ' + meta.col.type + '  —  click to sort, drag to reorder'"
            @click="onHeaderClick(meta.col, $event)"
            @dragstart="onDragStart(meta.col.name, $event)"
            @dragover.prevent="onDragOver(meta.col.name)"
            @drop.prevent="onDrop(meta.col.name)"
            @dragend="onDragEnd"
          >
            <Pin v-if="meta.pinned" class="h-3 w-3 shrink-0 text-primary" />
            <span
              class="truncate text-xs font-semibold text-ink-gray-7"
              :class="isNumericType(meta.col.type) ? 'tabular-nums' : ''"
            >
              {{ meta.col.name }}
            </span>
            <!-- Type chip (Batch 3 / Table) — small uppercase pill so the user can
                 read the column type at a glance without hovering. -->
            <span
              v-if="meta.col.type"
              class="shrink-0 rounded-2 px-1 text-[9px] font-medium uppercase tracking-wide text-ink-gray-4"
              :title="`${meta.col.name} · ${meta.col.type}`"
            >{{ meta.col.type }}</span>
            <span
              v-if="sortInfo(meta.col.name)"
              class="inline-flex shrink-0 items-center text-primary"
            >
              <ArrowUp v-if="sortInfo(meta.col.name)!.dir === 'asc'" class="h-3 w-3" />
              <ArrowDown v-else class="h-3 w-3" />
              <span v-if="sortSpec.length > 1" class="text-[9px] font-bold leading-none">{{ sortInfo(meta.col.name)!.idx }}</span>
            </span>
            <button
              type="button"
              class="ml-auto shrink-0 rounded-2 p-0.5 text-ink-gray-4 transition-colors hover:bg-surface-gray-3 hover:text-ink-gray-7"
              title="Column actions"
              draggable="false"
              @click.stop="toggleMenu(meta.col.name, $event)"
              @dragstart.stop.prevent
            >
              <MoreVertical class="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        <!-- Virtualized body: only the visible rows are in the DOM -->
        <div class="relative" :style="{ height: totalSize + 'px' }">
          <div
            v-for="vRow in virtualRows"
            :key="vRow.index"
            class="absolute top-0 left-0 flex border-b border-outline-gray-1 hover:bg-surface-gray-1"
            :style="{ height: vRow.size + 'px', transform: `translateY(${vRow.start}px)` }"
          >
            <div
              v-for="meta in displayCols"
              :key="meta.col.name"
              class="relative shrink-0 truncate px-3 py-2 text-xs text-ink-gray-8"
              :class="[
                meta.pinned ? 'z-[5] bg-surface-base' : '',
                isEditing(vRow.index, meta.col.name) ? '' : 'cursor-text',
                isNumericType(meta.col.type) ? 'text-right tabular-nums' : '',
              ]"
              :style="bodyCellStyle(meta, rows[vRow.index])"
              :title="isEditing(vRow.index, meta.col.name) ? '' : cell(rows[vRow.index], meta.col.name)"
              @dblclick="startEdit(vRow.index, meta.col.name)"
            >
              <input
                v-if="isEditing(vRow.index, meta.col.name)"
                ref="editInput"
                v-model="editValue"
                type="text"
                class="absolute inset-0 z-10 w-full border border-primary bg-surface-base px-3 text-xs text-ink-gray-9 focus:outline-none"
                :class="isNumericType(meta.col.type) ? 'text-right tabular-nums' : ''"
                @keydown.enter.prevent="commitEdit"
                @keydown.esc.prevent="cancelEdit"
                @blur="commitEdit"
                @click.stop
                @dblclick.stop
              />
              <template v-else>{{ cell(rows[vRow.index], meta.col.name) }}</template>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Column ⋮ menu (fixed-positioned; anchored to the clicked button). The
         transparent backdrop catches an outside click to dismiss. -->
    <div v-if="menuCol" class="fixed inset-0 z-40" @click="menuCol = null"></div>
    <div
      v-if="menuCol"
      class="fixed z-50 w-52 overflow-y-auto rounded-3 border border-outline-gray-1 bg-surface-base py-1 shadow-md"
      :style="menuStyle"
    >
      <div class="truncate px-3 py-1 text-[11px] font-medium uppercase tracking-wide text-ink-gray-4">
        {{ menuCol }}
      </div>
      <!-- View controls (grid-local; never mutate data) -->
      <button
        type="button"
        class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs font-medium text-ink-gray-8 transition-colors hover:bg-surface-gray-2"
        @click="togglePin"
      >
        <Pin class="h-3.5 w-3.5 text-primary" /> {{ menuPinned ? 'Unfreeze column' : 'Freeze (pin left)' }}
      </button>
      <button
        v-if="canHeatmap"
        type="button"
        class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs font-medium text-ink-gray-8 transition-colors hover:bg-surface-gray-2"
        @click="toggleHeatmap"
      >
        <BarChart3 class="h-3.5 w-3.5 text-primary" /> {{ menuHeat ? 'Remove colour scale' : 'Colour scale (heatmap)' }}
      </button>
      <button
        type="button"
        class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs font-medium text-ink-gray-8 transition-colors hover:bg-surface-gray-2"
        @click="hideFromMenu"
      >
        <Eye class="h-3.5 w-3.5 text-ink-gray-5" /> Hide column
      </button>
      <div class="my-1 border-t border-outline-gray-1"></div>
      <button
        type="button"
        class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs font-medium text-ink-gray-8 transition-colors hover:bg-surface-gray-2"
        @click="chooseProfile"
      >
        <BarChart3 class="h-3.5 w-3.5 text-primary" /> Profile column
      </button>
      <button
        type="button"
        class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs font-medium text-ink-gray-8 transition-colors hover:bg-surface-gray-2"
        @click="copyColumn"
      >
        <Copy class="h-3.5 w-3.5 text-ink-gray-5" /> Copy column values
      </button>
      <div class="my-1 border-t border-outline-gray-1"></div>
      <button
        v-for="item in COLUMN_OPS"
        :key="item.op"
        type="button"
        class="flex w-full items-center px-3 py-1.5 text-left text-xs text-ink-gray-8 transition-colors hover:bg-surface-gray-2"
        @click="chooseOp(item.op)"
      >
        {{ item.label }}
      </button>
    </div>

    <!-- Export format menu (fixed-positioned; anchored to the Export button). Every
         format is encoded server-side, so the download always reflects the cleaned table. -->
    <div v-if="exportMenuOpen" class="fixed inset-0 z-40" @click="exportMenuOpen = false"></div>
    <div
      v-if="exportMenuOpen"
      class="fixed z-50 w-48 overflow-hidden rounded-3 border border-outline-gray-1 bg-surface-base py-1 shadow-md"
      :style="{ top: exportMenuPos.y + 4 + 'px', left: exportMenuPos.x + 'px', transform: 'translateX(-100%)' }"
    >
      <div class="px-3 py-1 text-[11px] font-medium uppercase tracking-wide text-ink-gray-4">
        Export table as
      </div>
      <button
        v-for="f in EXPORT_FORMATS"
        :key="f.fmt"
        type="button"
        class="flex w-full items-center px-3 py-1.5 text-left text-xs text-ink-gray-8 transition-colors hover:bg-surface-gray-2"
        @click="exportAs(f.fmt, f.ext)"
      >
        {{ f.label }}
      </button>
    </div>

    <!-- Columns show/hide menu (fixed-positioned; lists ALL columns so a hidden one
         can be brought back). Toggling only affects the grid's rendered columns. -->
    <div v-if="colMenuOpen" class="fixed inset-0 z-40" @click="colMenuOpen = false"></div>
    <div
      v-if="colMenuOpen"
      class="fixed z-50 max-h-[320px] w-56 overflow-auto rounded-3 border border-outline-gray-1 bg-surface-base py-1 shadow-md"
      :style="{ top: colMenuPos.y + 4 + 'px', left: colMenuPos.x + 'px', transform: 'translateX(-100%)' }"
    >
      <div class="flex items-center justify-between px-3 py-1">
        <span class="text-[11px] font-medium uppercase tracking-wide text-ink-gray-4">Columns</span>
        <button
          type="button"
          class="text-[11px] text-ink-gray-4 transition-colors hover:text-ink-gray-7"
          @click="showAllCols"
        >
          Show all
        </button>
      </div>
      <label
        v-for="col in columns"
        :key="col.name"
        class="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-ink-gray-8 transition-colors hover:bg-surface-gray-2"
      >
        <input
          type="checkbox"
          class="h-3.5 w-3.5 shrink-0 rounded border-outline-gray-3 text-primary focus:ring-0"
          :checked="!hiddenCols.has(col.name)"
          @change="toggleColVisible(col.name)"
        />
        <span class="truncate">{{ col.name }}</span>
      </label>
    </div>
  </div>
</template>
