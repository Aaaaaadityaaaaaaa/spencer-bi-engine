<script setup lang="ts">
// The Canvas dashboard container: the ONLY place that fetches aggregates.
//
// Tiles (KpiCard / ChartTile) are presentational + own their pickers; they emit config
// changes upward and this component re-runs the affected aggregation. Centralising the
// data layer is what makes "clean the data in the Table tab -> the whole dashboard
// refreshes" a single `dataVersion` watch instead of N independent subscriptions.
//
// Power BI–style Canvas (TASK-034): KPI cards and charts share ONE freeform, movable +
// resizable grid (grid-layout-plus). The board is organised into named PAGES; each page
// owns its own tiles + grid layout. Everything auto-persists per user (TASK-033, "persist
// immediately"): every edit / move / resize / page change snapshots the live board to
// localStorage via useActiveDashboard, so a reload restores the exact multi-page board
// (matched by sessionUuid; a foreign/absent session seeds fresh). NAMED save/load slots
// are useDashboards' job, wired into the header here (TASK-035).
import { computed, onActivated, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { GridLayout, GridItem } from 'grid-layout-plus'
import ErrorBoundary from './ErrorBoundary.vue'
import { AlertCircle, BookMarked, FileDown, Filter, ImageDown, LayoutDashboard, Loader2, Maximize, Pencil, Plus, RefreshCw, Save, Settings, Sparkles, Trash2, X } from '@lucide/vue'
import { toPng } from 'html-to-image'
import { jsPDF } from 'jspdf'
import type {
  AggregateFilter,
  AggregateKey,
  AggregateResponse,
  AggregateValue,
  ChartConfig,
  ColumnMeta,
  DashboardPage,
  KpiConfig,
  PersistedChartEntry,
  TileState,
} from '../types'
import { supportsBreakdown } from '../types'
import { useSession } from '../composables/useSession'
import { persistActiveDashboard, readActiveDashboard } from '../composables/useActiveDashboard'
import { useDashboards } from '../composables/useDashboards'
import { useToasts } from '../composables/useToast'
import { useCanvasSeed } from '../composables/useCanvasSeed'
import { useTileDrawer } from '../composables/useTileDrawer'
import { apiErrorMessage, fetchAggregate, narrateDataset } from '../services/api'
import { categoricalColumns, numericColumns, temporalColumns } from '../utils/columnKind'
import {
  CHART_H,
  CHART_MIN_H,
  CHART_MIN_W,
  CHART_W,
  GRID_COLS,
  GRID_MARGIN,
  GRID_ROW_HEIGHT,
  KPI_H,
  KPI_MIN_H,
  KPI_MIN_W,
  KPI_W,
  chartTileId,
  generateFlowLayout,
  kpiTileId,
  layoutBottom,
  parseTileId,
} from '../utils/dashboardLayout'
import KpiCard from './KpiCard.vue'
import ChartTile from './ChartTile.vue'
import DashboardSettingsModal from './DashboardSettingsModal.vue'
import EmptyState from './EmptyState.vue'
import { dashboardSettings } from '../composables/useDashboardSettings'

const { sessionUuid, tableName, columns, rowCount, dataVersion } = useSession()
const { takePendingSeed } = useCanvasSeed()

const MAX_KPIS = 6 // per page
const MAX_CHARTS = 6 // per page
const MAX_PAGES = 12
const SERIES_LIMIT = 50 // top-N categories; the server clamps to 200.
const TOPN_CAP = 200 // TASK-036: hard ceiling for a per-chart "Top N" (matches the server MAX_CATEGORIES).
const TREND_LIMIT = 200 // #14 sparkline points; the server clamps a temporal series to 200.
const PERSIST_DEBOUNCE_MS = 250 // a drag/resize mutates the layout many times; coalesce writes.
const BLANK: TileState<AggregateValue> = { loading: false, error: null, data: null }
const BLANK_CHART: TileState<AggregateResponse> = { loading: false, error: null, data: null }

// Power BI–style global settings window (#request: report-level formatting instead of per-tile).
const showSettings = ref(false)
function applyAllToTiles(): void {
  for (const p of pages.value) {
    for (const c of p.charts) {
      c.config.showValues = dashboardSettings.showValues
      if (dashboardSettings.accent) c.config.color = dashboardSettings.accent
    }
  }
  persistNow()
  showSettings.value = false
}

// Per-visual settings drawer (Power BI–style): clicking a tile opens its editor in a side
// panel instead of inline controls. State lives in the shared composable so the drawer chrome
// can sit at the app root (see App.vue) while tiles teleport their editor into it.
const { selectedTile, openTileDrawer, closeTileDrawer, isTileSelected } = useTileDrawer()
function isSelected(kind: 'kpi' | 'chart', id: number): boolean {
  return isTileSelected(kind, id)
}
function openTileSettings(kind: 'kpi' | 'chart', id: number): void {
  openTileDrawer(kind, id, columns.value)
}

// A chart tile = an id + its config (PersistedChartEntry). ChartConfig stays id-free (it is
// the pure query + render spec); the id lives on the wrapper so tiles can be added/removed
// and their fetch state keyed independently, exactly like the KPI cards.
type ChartEntry = PersistedChartEntry

// --- Pages (TASK-034) ------------------------------------------------------------
// The board is a list of pages; the active one is what renders. `kpis`/`charts`/`layout`
// are read-only views over the active page, so all the fetch/edit/cross-filter code below
// reads them unchanged — add/remove/page ops mutate the page objects directly.
const pages = ref<DashboardPage[]>([])
const activePageId = ref<string>('')
const activePage = computed<DashboardPage | null>(
  () => pages.value.find((p) => p.id === activePageId.value) ?? null,
)
const kpis = computed<KpiConfig[]>(() => activePage.value?.kpis ?? [])
const charts = computed<ChartEntry[]>(() => activePage.value?.charts ?? [])
const layout = computed(() => activePage.value?.layout ?? [])

// Fetch state is keyed by the tile's GLOBALLY-unique numeric id (ids are minted across all
// pages), so a tile keeps its data even while another page is showing. Only the active
// page's tiles are rendered + refetched.
const kpiState = reactive<Record<number, TileState<AggregateValue> | undefined>>({})
// #14 sparkline: each KPI's metric-over-time series, fetched in parallel with its scalar.
const kpiTrend = reactive<Record<number, TileState<AggregateResponse> | undefined>>({})
const chartStates = reactive<Record<number, TileState<AggregateResponse> | undefined>>({})

// O(1) lookups from a composite tile id back to its config, for the grid's v-for.
const kpiById = computed<Record<number, KpiConfig>>(() => {
  const m: Record<number, KpiConfig> = {}
  for (const k of kpis.value) m[k.id] = k
  return m
})
const chartById = computed<Record<number, ChartEntry>>(() => {
  const m: Record<number, ChartEntry> = {}
  for (const c of charts.value) m[c.id] = c
  return m
})
function kpiByTile(i: string): KpiConfig | undefined {
  const p = parseTileId(i)
  return p?.kind === 'kpi' ? kpiById.value[p.id] : undefined
}
function chartByTile(i: string): ChartEntry | undefined {
  const p = parseTileId(i)
  return p?.kind === 'chart' ? chartById.value[p.id] : undefined
}
// A chart tile can shrink less than a KPI (it must stay readable); the grid enforces these.
function minWFor(i: string): number {
  return parseTileId(i)?.kind === 'chart' ? CHART_MIN_W : KPI_MIN_W
}
function minHFor(i: string): number {
  return parseTileId(i)?.kind === 'chart' ? CHART_MIN_H : KPI_MIN_H
}

// The single active cross-filter (Power-BI-style slicer). Clicking a bar/slice sets it;
// every KPI and every OTHER chart re-fetches filtered by it, while the source tile keeps
// showing all categories (with the clicked one highlighted) so another can be picked.
interface CrossFilter {
  column: string
  value: AggregateKey
  sourceId: number
}
const crossFilter = ref<CrossFilter | null>(null)

// #29 data-storytelling state (the tellStory action is defined lower). Declared here so
// the session/dataVersion watches below — one of which runs immediately at setup — can
// clear the narrative without hitting a temporal-dead-zone on a later const.
const narrating = ref(false)
const story = ref<string | null>(null)
const storyError = ref<string | null>(null)

// The `filters` payload for a tile's request: the active slice, unless this IS the tile
// that owns it (the source shows its full series). Returns undefined when there is no
// slice or the tile is the source — JSON.stringify then omits the key entirely.
function filtersFor(sourceId?: number): AggregateFilter[] | undefined {
  const f = crossFilter.value
  if (!f || f.sourceId === sourceId) return undefined
  return [{ column: f.column, value: f.value }]
}

// The highlight key handed to a tile: set only on the source tile, undefined elsewhere
// (so a real null key stays distinct from "this tile isn't the source").
function activeKeyFor(id: number): AggregateKey | undefined {
  const f = crossFilter.value
  return f && f.sourceId === id ? f.value : undefined
}

function displayKey(v: AggregateKey): string {
  return v === null ? '(null)' : String(v)
}

// The breakdown column actually SENT for a chart: only the breakdown-capable chart
// types (bar/line/area/stacked/heatmap) read `series`; for the rest we send null so a
// stale breakdown left over from a previous type can never turn a 1-D render (pie,
// treemap, funnel, hbar) into an empty 2-D matrix. Also the unit the stale-query guard
// compares, so a type switch that flips breakdown support correctly refetches.
function effectiveSeries(cfg: ChartConfig): string | null {
  return supportsBreakdown(cfg.chartType) ? (cfg.series ?? null) : null
}

// Tile-id counters resume PAST every restored id (across ALL pages), or the next Add would
// mint a colliding id and its fetch state would clobber a live tile's.
let nextKpiId = 1
let nextChartId = 1
function resetCountersFromPages(): void {
  let k = 0
  let c = 0
  for (const p of pages.value) {
    for (const kpi of p.kpis) k = Math.max(k, kpi.id)
    for (const ch of p.charts) c = Math.max(c, ch.id)
  }
  nextKpiId = k + 1
  nextChartId = c + 1
}

// Page ids are opaque + stable for the session; a base-36 timestamp + counter can't collide
// with the upgrade path's fixed "page-1" or with each other.
let pageCounter = 0
function makePageId(): string {
  pageCounter += 1
  return `pg-${Date.now().toString(36)}-${pageCounter}`
}

// Monotonic request counters, one per tile (same guard OpDialog uses for its dry-run
// previews). A slow response from an older config must never overwrite a newer one.
const kpiSeq: Record<number, number> = {}
const kpiTrendSeq: Record<number, number> = {}
const chartSeq: Record<number, number> = {}

const anyLoading = computed(
  () =>
    charts.value.some((c) => chartStateOf(c.id).loading) ||
    kpis.value.some((k) => kpiState[k.id]?.loading === true),
)

function chartStateOf(id: number): TileState<AggregateResponse> {
  return chartStates[id] ?? BLANK_CHART
}
// Replace the whole state object (never mutate in place): a freshly-inserted plain
// object would bypass the reactive proxy and the tile would not re-render.
function setChartState(id: number, patch: Partial<TileState<AggregateResponse>>): void {
  chartStates[id] = { ...(chartStates[id] ?? BLANK_CHART), ...patch }
}

function kpiStateOf(id: number): TileState<AggregateValue> {
  return kpiState[id] ?? BLANK
}
function setKpiState(id: number, patch: Partial<TileState<AggregateValue>>): void {
  kpiState[id] = { ...(kpiState[id] ?? BLANK), ...patch }
}

function kpiTrendOf(id: number): TileState<AggregateResponse> {
  return kpiTrend[id] ?? BLANK_CHART
}
function setKpiTrend(id: number, patch: Partial<TileState<AggregateResponse>>): void {
  kpiTrend[id] = { ...(kpiTrend[id] ?? BLANK_CHART), ...patch }
}

// Drop every tile's fetch state (on a dataset swap or a whole-board load), so stale data
// from the previous board can't flash under the new one.
function clearAllTileState(): void {
  for (const key of Object.keys(kpiState)) delete kpiState[Number(key)]
  for (const key of Object.keys(kpiTrend)) delete kpiTrend[Number(key)]
  for (const key of Object.keys(chartStates)) delete chartStates[Number(key)]
}

// --- Auto-seed -------------------------------------------------------------------
// A dashboard should exist the instant a file lands, so the first tiles are inferred
// from the schema; every one of them is editable afterwards.
function buildSeed(cols: ColumnMeta[]): { kpis: KpiConfig[]; charts: ChartEntry[] } {
  const nums = numericColumns(cols)
  const cats = categoricalColumns(cols)
  const temps = temporalColumns(cols)

  const seeded: KpiConfig[] = [{ id: nextKpiId++, measure: null, aggregation: 'count' }]
  if (nums.length > 0) {
    seeded.push({ id: nextKpiId++, measure: nums[0].name, aggregation: 'sum' })
    seeded.push({ id: nextKpiId++, measure: nums[0].name, aggregation: 'avg' })
    if (nums.length > 1) {
      seeded.push({ id: nextKpiId++, measure: nums[1].name, aggregation: 'sum' })
    }
  } else if (cats.length > 0) {
    // Nothing to sum: the next most useful number is "how many distinct values".
    seeded.push({ id: nextKpiId++, measure: cats[0].name, aggregation: 'count_distinct' })
  }
  // #14: auto-seed a trend axis so KPI cards show a sparkline the instant a file with a
  // date column lands (mirrors the auto-dashboard philosophy). Clearable to None per card.
  const trendDim = temps[0]?.name ?? null
  if (trendDim) for (const k of seeded) k.trendDimension = trendDim

  // Prefer a categorical column that actually groups (cardinality > 1) and stays
  // readable (<= 50 bars). `cardinality` is optional, so an unknown one is allowed
  // through rather than excluded.
  const grouping = cats.filter((c) => c.cardinality === undefined || c.cardinality > 1)
  const readable = grouping.find((c) => c.cardinality !== undefined && c.cardinality <= 50)
  const dim = readable ?? grouping[0] ?? temps[0] ?? null
  const isTemporal = dim !== null && temps.some((t) => t.name === dim.name)

  const chartsSeed: ChartEntry[] = [
    {
      id: nextChartId++,
      config: {
        dimension: dim?.name ?? null,
        series: null,
        measure: nums[0]?.name ?? null,
        aggregation: nums.length > 0 ? 'sum' : 'count',
        chartType: isTemporal ? 'line' : 'bar',
      },
    },
  ]

  // #Batch4: seed a SECOND chart when the data supports a different angle. A categorical
  // breakdown alongside the first chart gives the board a richer, ready-made story instead
  // of one lonely visual. We only add it when (a) there's a non-temporal categorical column
  // the first chart isn't already using, and (b) its cardinality stays readable (<= 50 bars).
  const extraCats = cats.filter(
    (c) => !isTemporal && c.name !== (dim?.name ?? null) && (c.cardinality === undefined || c.cardinality <= 50),
  )
  if (extraCats.length > 0) {
    const by = extraCats[0]
    chartsSeed.push({
      id: nextChartId++,
      config: {
        dimension: by.name,
        series: null,
        measure: nums[0]?.name ?? null,
        aggregation: nums.length > 0 ? 'sum' : 'count',
        chartType: 'bar',
      },
    })
  }

  return { kpis: seeded, charts: chartsSeed }
}

// A fresh page with an auto-seeded set of tiles + a flow layout (KPIs across the top,
// charts below), so a new dataset opens on a usable dashboard rather than a blank grid.
function makeSeededPage(name: string): DashboardPage {
  const { kpis: k, charts: c } = buildSeed(columns.value)
  const tiles = generateFlowLayout(
    k.map((x) => x.id),
    c.map((x) => x.id),
  )
  return { id: makePageId(), name, kpis: k, charts: c, layout: tiles }
}

// Defensive: drop layout items with no matching tile (orphaned by a hand-edited blob) and
// append any tile missing a layout item at the bottom, so a restored page always renders
// every tile exactly once. Normally a no-op — add/remove keep layout in lockstep.
function reconcilePageLayout(page: DashboardPage): void {
  const valid = new Set<string>()
  for (const k of page.kpis) valid.add(kpiTileId(k.id))
  for (const c of page.charts) valid.add(chartTileId(c.id))
  page.layout = page.layout.filter((it) => valid.has(it.i))
  const present = new Set(page.layout.map((it) => it.i))
  let y = layoutBottom(page.layout)
  for (const k of page.kpis) {
    const i = kpiTileId(k.id)
    if (!present.has(i)) {
      page.layout.push({ i, x: 0, y, w: KPI_W, h: KPI_H })
      y += KPI_H
    }
  }
  for (const c of page.charts) {
    const i = chartTileId(c.id)
    if (!present.has(i)) {
      page.layout.push({ i, x: 0, y, w: CHART_W, h: CHART_H })
      y += CHART_H
    }
  }
}

// --- Fetching --------------------------------------------------------------------
async function loadKpi(cfg: KpiConfig): Promise<void> {
  const uuid = sessionUuid.value
  if (!uuid) return
  const seq = (kpiSeq[cfg.id] ?? 0) + 1
  kpiSeq[cfg.id] = seq
  setKpiState(cfg.id, { loading: true, error: null })
  try {
    const resp = await fetchAggregate(
      uuid,
      {
        dimension: null,
        measure: cfg.measure,
        aggregation: cfg.aggregation,
        filters: filtersFor(),
      },
      tableName.value ?? undefined,
    )
    // Stale on either axis: a newer config for this tile, or a different session.
    if (seq !== kpiSeq[cfg.id] || uuid !== sessionUuid.value) return
    setKpiState(cfg.id, { loading: false, error: null, data: resp.values[0] ?? null })
  } catch (e) {
    if (seq !== kpiSeq[cfg.id] || uuid !== sessionUuid.value) return
    // A 400 here is usually "column no longer exists" after a drop/rename; the card
    // renders it as an invitation to reconfigure rather than crashing the dashboard.
    setKpiState(cfg.id, { loading: false, error: apiErrorMessage(e), data: null })
  }
}

// #14 sparkline: the card's metric grouped by its chosen temporal column. A separate
// aggregate from the scalar (dimension != null), guarded by its own seq so a slow
// response can't overwrite a newer one. No dimension => clear the series (no fetch).
async function loadKpiTrend(cfg: KpiConfig): Promise<void> {
  const id = cfg.id
  if (!cfg.trendDimension) {
    // Bump the seq so any trend response already in flight for this card is discarded.
    kpiTrendSeq[id] = (kpiTrendSeq[id] ?? 0) + 1
    setKpiTrend(id, { loading: false, error: null, data: null })
    return
  }
  const uuid = sessionUuid.value
  if (!uuid) return
  const seq = (kpiTrendSeq[id] ?? 0) + 1
  kpiTrendSeq[id] = seq
  setKpiTrend(id, { loading: true, error: null })
  try {
    const resp = await fetchAggregate(
      uuid,
      {
        dimension: cfg.trendDimension,
        measure: cfg.measure,
        aggregation: cfg.aggregation,
        limit: TREND_LIMIT,
        filters: filtersFor(),
      },
      tableName.value ?? undefined,
    )
    if (seq !== kpiTrendSeq[id] || uuid !== sessionUuid.value) return
    setKpiTrend(id, { loading: false, error: null, data: resp })
  } catch (e) {
    if (seq !== kpiTrendSeq[id] || uuid !== sessionUuid.value) return
    // The trend is decorative: on error (e.g. the trend column was dropped) just clear
    // the series so no sparkline renders -- the scalar card still shows its own value.
    setKpiTrend(id, { loading: false, error: apiErrorMessage(e), data: null })
  }
}

async function loadChart(entry: ChartEntry): Promise<void> {
  const uuid = sessionUuid.value
  const cfg = entry.config
  if (!uuid) return
  if (cfg.dimension === null) {
    // No group-by ⇒ nothing to plot; skip the round trip and let the tile prompt.
    // Still bump the seq so any response already in flight for this tile is discarded.
    chartSeq[entry.id] = (chartSeq[entry.id] ?? 0) + 1
    setChartState(entry.id, { loading: false, error: null, data: null })
    return
  }
  const seq = (chartSeq[entry.id] ?? 0) + 1
  chartSeq[entry.id] = seq
  setChartState(entry.id, { loading: true, error: null })
  try {
    const resp = await fetchAggregate(
      uuid,
      {
        dimension: cfg.dimension,
        series: effectiveSeries(cfg),
        measure: cfg.measure,
        aggregation: cfg.aggregation,
        // Wave 5 scatter: a Y measure turns the request into a raw point cloud. Only sent
        // when present; ignored by the backend for non-scatter types anyway.
        ...(cfg.measureY ? { measure_y: cfg.measureY, top_points: 1000 } : {}),
        // Wave 5 box plot: group `measure` by `dimension` for per-category stats.
        ...(cfg.chartType === 'box' ? { box: true } : {}),
        // TASK-036 #4: per-chart Top-N. null/absent ⇒ the default SERIES_LIMIT (unchanged
        // behaviour). The server sorts a categorical series by measure DESC then clamps, so
        // a smaller limit yields the TRUE top-N; clamp here too to never send an absurd value.
        limit: Math.max(1, Math.min(cfg.topN ?? SERIES_LIMIT, TOPN_CAP)),
        filters: filtersFor(entry.id),
      },
      tableName.value ?? undefined,
    )
    // Stale on either axis: a newer config for this tile, or a different session.
    if (seq !== chartSeq[entry.id] || uuid !== sessionUuid.value) return
    setChartState(entry.id, { loading: false, error: null, data: resp })
  } catch (e) {
    if (seq !== chartSeq[entry.id] || uuid !== sessionUuid.value) return
    setChartState(entry.id, { loading: false, error: apiErrorMessage(e), data: null })
  }
}

// Tiles are independent: one failing aggregation must not blank the others. Scoped to the
// ACTIVE page's tiles (kpis/charts are the active-page views).
function loadAll(): void {
  for (const cfg of kpis.value) {
    void loadKpi(cfg)
    void loadKpiTrend(cfg)
  }
  for (const entry of charts.value) void loadChart(entry)
}

// --- Persistence ("persist immediately") -----------------------------------------
// Snapshot the whole multi-page board to per-user localStorage. `persistNow` writes
// synchronously (seed + gesture-end commits); `schedulePersist` debounces the deep-watch
// firehose (a drag mutates the layout on every pointermove).
function persistNow(): void {
  const uuid = sessionUuid.value
  if (!uuid) return
  persistActiveDashboard(uuid, { pages: pages.value, activePageId: activePageId.value })
}
let persistTimer: ReturnType<typeof setTimeout> | null = null
function schedulePersist(): void {
  const uuid = sessionUuid.value
  if (!uuid) return
  if (persistTimer) clearTimeout(persistTimer)
  persistTimer = setTimeout(() => {
    persistTimer = null
    // Re-check the session: it may have gone null/changed during the debounce window.
    if (sessionUuid.value === uuid) {
      persistActiveDashboard(uuid, { pages: pages.value, activePageId: activePageId.value })
    }
  }, PERSIST_DEBOUNCE_MS)
}

// --- Reactions -------------------------------------------------------------------
// New session (or a "Replace dataset"): throw the old dashboard away and re-seed, OR
// restore the exact multi-page board saved for THIS dataset (same user + same sessionUuid).
watch(
  sessionUuid,
  (uuid) => {
    clearAllTileState()
    pages.value = []
    activePageId.value = ''
    crossFilter.value = null
    story.value = null
    storyError.value = null
    nextKpiId = 1
    nextChartId = 1
    if (!uuid) return
    // readActiveDashboard upgrades a pre-grid v1 blob to the multi-page v2 shape, so a board
    // saved before the grid upgrade still restores. Adopt only when it's THIS dataset.
    const restored = readActiveDashboard()
    if (restored && restored.sessionUuid === uuid && restored.pages.length > 0) {
      pages.value = restored.pages
      activePageId.value = restored.activePageId
      resetCountersFromPages()
      for (const p of pages.value) reconcilePageLayout(p)
    } else {
      const page = makeSeededPage('Page 1')
      pages.value = [page]
      activePageId.value = page.id
    }
    // Persist NOW, for BOTH paths: the deep watch below is registered after this (immediate)
    // watch, so it never observes this synchronous seed/adopt mutation — only later edits.
    // Writing here means (a) a freshly-seeded board survives a reload with no edit, and
    // (b) an upgraded v1 blob is migrated to v2 on disk on first load rather than being
    // re-upgraded from v1 on every reload. Safe: it writes exactly what we just put in memory
    // for this uuid (a no-op-equivalent rewrite for a v2 restore).
    persistNow()
    loadAll()
  },
  { immediate: true },
)

// "Persist immediately": snapshot the live board on every edit (add / remove / reconfigure /
// title / color / values / clean / move / resize / page change). Debounced so a drag gesture
// coalesces to one write. Guarded on a null session inside schedulePersist so the reset-to-[]
// that fires on logout or dataset-replace never stomps a good blob with empties.
watch([pages, activePageId], schedulePersist, { deep: true })

// Bumped by useSession after every transform / undo / redo. Configs are kept; only
// the numbers are re-read, which is what makes cleaning visibly move the dashboard.
watch(dataVersion, () => {
  if (!sessionUuid.value) return
  // A transform may have dropped/renamed the cross-filter column; if so the slice is no
  // longer meaningful (and would 400 every filtered tile), so drop it before refetching.
  const f = crossFilter.value
  if (f && !columns.value.some((c) => c.name === f.column)) crossFilter.value = null
  // The schema may have changed, so the shown narrative could now be wrong — drop it and
  // let the user re-request (the server cache keys on schema_version, so it stays cheap).
  story.value = null
  storyError.value = null
  loadAll()
})

// --- Edits -----------------------------------------------------------------------
function onKpiUpdate(cfg: KpiConfig): void {
  const i = kpis.value.findIndex((k) => k.id === cfg.id)
  if (i === -1) return
  const prev = kpis.value[i]
  kpis.value[i] = cfg
  // target/targetMode are pure display (#14) and refetch nothing. The scalar refetches
  // only on a query change; the trend (#14 sparkline) additionally refetches when its
  // own axis (trendDimension) changes -- it shares the card's measure/aggregation.
  const queryChanged = prev.measure !== cfg.measure || prev.aggregation !== cfg.aggregation
  if (queryChanged) void loadKpi(cfg)
  if (queryChanged || prev.trendDimension !== cfg.trendDimension) void loadKpiTrend(cfg)
}

function onKpiRemove(id: number): void {
  const page = activePage.value
  if (!page) return
  if (selectedTile.value?.kind === 'kpi' && selectedTile.value.id === id) closeTileDrawer()
  page.kpis = page.kpis.filter((k) => k.id !== id)
  page.layout = page.layout.filter((it) => it.i !== kpiTileId(id))
  delete kpiState[id]
  delete kpiSeq[id]
  delete kpiTrend[id]
  delete kpiTrendSeq[id]
}

// TASK-044: clone a KPI in place (same config, fresh id) so users can build from a copy.
function onKpiDuplicate(id: number): void {
  const page = activePage.value
  if (!page) return
  const src = page.kpis.find((k) => k.id === id)
  if (!src) return
  const cfg: KpiConfig = { ...src, id: nextKpiId++ }
  page.kpis.push(cfg)
  page.layout.push({ i: kpiTileId(cfg.id), x: 0, y: layoutBottom(page.layout), w: KPI_W, h: KPI_H })
  void loadKpi(cfg)
  void loadKpiTrend(cfg)
}

function addKpi(): void {
  const page = activePage.value
  if (!page || page.kpis.length >= MAX_KPIS) return
  // Start from COUNT(*): always valid whatever the schema looks like. Inherit the same
  // auto-trend axis the seeded cards use so a new card matches them (clearable to None).
  const cfg: KpiConfig = {
    id: nextKpiId++,
    measure: null,
    aggregation: 'count',
    trendDimension: temporalColumns(columns.value)[0]?.name ?? null,
  }
  page.kpis.push(cfg)
  page.layout.push({ i: kpiTileId(cfg.id), x: 0, y: layoutBottom(page.layout), w: KPI_W, h: KPI_H })
  void loadKpi(cfg)
  void loadKpiTrend(cfg)
}

function onChartUpdate(id: number, cfg: ChartConfig): void {
  const i = charts.value.findIndex((c) => c.id === id)
  if (i === -1) return
  const prev = charts.value[i].config
  charts.value[i] = { id, config: cfg }
  // `chartType` is a pure rendering concern -- redrawing an existing series from the
  // same data must not cost a round trip. Only the query fields refetch (and a tile with
  // no data yet retries, so a type switch can recover from an earlier failure). The
  // EFFECTIVE breakdown is part of the query: switching to/from a breakdown-capable type,
  // or changing the breakdown column, flips 1-D <-> 2-D output and must refetch.
  const sameQuery =
    prev.dimension === cfg.dimension &&
    prev.measure === cfg.measure &&
    prev.aggregation === cfg.aggregation &&
    // TASK-036: Top-N is a query field (it changes the row set the server returns), so a
    // change must refetch. `?? null` folds undefined/null together ⇒ no spurious refetch.
    (prev.topN ?? null) === (cfg.topN ?? null) &&
    effectiveSeries(prev) === effectiveSeries(cfg)
  if (!sameQuery || chartStateOf(id).data === null) void loadChart(charts.value[i])
}

function onChartRemove(id: number): void {
  const page = activePage.value
  if (!page) return
  if (selectedTile.value?.kind === 'chart' && selectedTile.value.id === id) closeTileDrawer()
  page.charts = page.charts.filter((c) => c.id !== id)
  page.layout = page.layout.filter((it) => it.i !== chartTileId(id))
  delete chartStates[id]
  delete chartSeq[id]
  // Removing the tile that owns the cross-filter clears it and un-filters the rest.
  if (crossFilter.value?.sourceId === id) {
    crossFilter.value = null
    loadAll()
  }
}

// TASK-044: clone a chart in place (same config, fresh id) so users can build from a copy.
function onChartDuplicate(id: number): void {
  const page = activePage.value
  if (!page) return
  const src = page.charts.find((c) => c.id === id)
  if (!src) return
  const entry: ChartEntry = { id: nextChartId++, config: { ...src.config } }
  page.charts.push(entry)
  page.layout.push({ i: chartTileId(entry.id), x: 0, y: layoutBottom(page.layout), w: CHART_W, h: CHART_H })
  void loadChart(entry)
}

function addChart(): void {
  const page = activePage.value
  if (!page || page.charts.length >= MAX_CHARTS) return
  // Start blank (no dimension) -> the tile shows its "choose a dimension" prompt.
  const entry: ChartEntry = {
    id: nextChartId++,
    config: {
      dimension: null,
      series: null,
      measure: null,
      aggregation: 'count',
      chartType: 'bar',
      showValues: dashboardSettings.showValues,
    },
  }
  page.charts.push(entry)
  page.layout.push({ i: chartTileId(entry.id), x: 0, y: layoutBottom(page.layout), w: CHART_W, h: CHART_H })
  void loadChart(entry)
}

// grid-layout-plus mutates the layout items IN PLACE during a drag/resize, so `page.layout`
// is already current by the time this fires on gesture-end; we just commit it immediately
// (the debounced deep watch would catch it too, but a synchronous write on gesture-end is
// snappier and survives an immediate reload).
function onLayoutUpdated(): void {
  persistNow()
}

// --- Cross-filter (Power-BI-style slicer) ----------------------------------------
// A bar/slice click sets the active slice; clicking the SAME value on the same tile again
// clears it, then refetches everything: KPIs + other charts filter down while the source
// tile stays whole with the clicked category highlighted.
function onChartSelect(sourceId: number, key: AggregateKey): void {
  const entry = charts.value.find((c) => c.id === sourceId)
  if (!entry || entry.config.dimension === null) return
  const dimension = entry.config.dimension
  const f = crossFilter.value
  if (f && f.sourceId === sourceId && f.column === dimension && f.value === key) {
    crossFilter.value = null
  } else {
    crossFilter.value = { column: dimension, value: key, sourceId }
  }
  loadAll()
}

function clearCrossFilter(): void {
  crossFilter.value = null
  loadAll()
}

// --- Pages -----------------------------------------------------------------------
function switchPage(id: string): void {
  if (id === activePageId.value || !pages.value.some((p) => p.id === id)) return
  activePageId.value = id
  // A cross-filter is a per-view slice; clear it so the new page starts unfiltered.
  crossFilter.value = null
  loadAll()
}

function addPage(): void {
  if (pages.value.length >= MAX_PAGES) return
  const page: DashboardPage = {
    id: makePageId(),
    name: `Page ${pages.value.length + 1}`,
    kpis: [],
    charts: [],
    layout: [],
  }
  pages.value = [...pages.value, page]
  activePageId.value = page.id
  crossFilter.value = null
}

function deletePage(id: string): void {
  if (pages.value.length <= 1) return // always keep at least one page
  const idx = pages.value.findIndex((p) => p.id === id)
  if (idx === -1) return
  const page = pages.value[idx]
  const tileCount = page.kpis.length + page.charts.length
  // Deleting a populated page is hard to reverse (it persists immediately), so confirm.
  if (tileCount > 0 && !window.confirm(`Delete "${page.name}" and its ${tileCount} tile(s)?`)) return
  for (const k of page.kpis) {
    delete kpiState[k.id]
    delete kpiSeq[k.id]
    delete kpiTrend[k.id]
    delete kpiTrendSeq[k.id]
  }
  for (const c of page.charts) {
    delete chartStates[c.id]
    delete chartSeq[c.id]
  }
  const wasActive = activePageId.value === id
  pages.value = pages.value.filter((p) => p.id !== id)
  if (wasActive) {
    // Fall to the neighbour that slid into this slot (or the new last page).
    activePageId.value = pages.value[Math.min(idx, pages.value.length - 1)].id
    crossFilter.value = null
    loadAll()
  }
}

function renamePage(id: string, name: string): void {
  const clean = name.trim()
  const page = pages.value.find((p) => p.id === id)
  if (!page || !clean) return
  page.name = clean
}

// Inline page rename (QueryConsole savingName idiom). One tab renames at a time; the input's
// ref callback focuses + selects it on mount (avoids a v-for ref array).
const renamingPageId = ref<string | null>(null)
const pageNameDraft = ref('')
function startRenamePage(page: DashboardPage): void {
  renamingPageId.value = page.id
  pageNameDraft.value = page.name
}
function confirmRenamePage(): void {
  if (renamingPageId.value) renamePage(renamingPageId.value, pageNameDraft.value)
  renamingPageId.value = null
}
function focusOnMount(el: unknown): void {
  if (el instanceof HTMLInputElement) {
    el.focus()
    el.select()
  }
}

// --- #15 named Save/Load slots (TASK-035) ----------------------------------------
const { dashboards, saveDashboard, loadDashboard, renameDashboard, deleteDashboard } = useDashboards()
const { pushToast } = useToasts()
const savedOpen = ref(false)
const savedPos = ref<{ x: number; y: number }>({ x: 0, y: 0 })
const saveName = ref('')
const renamingSavedId = ref<number | null>(null)
const savedNameDraft = ref('')

function toggleSaved(e: MouseEvent): void {
  if (savedOpen.value) {
    savedOpen.value = false
    return
  }
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  savedPos.value = { x: r.right, y: r.bottom }
  savedOpen.value = true
  renamingSavedId.value = null
}

function saveCurrentDashboard(): void {
  const name = saveName.value.trim()
  if (!name) return
  // useDashboards deep-clones, so the saved slot is severed from the live reactive board.
  if (sessionUuid.value) { saveDashboard(sessionUuid.value, name, { pages: pages.value, activePageId: activePageId.value }) }
  saveName.value = ''
  pushToast('Dashboard "' + name + '" saved', 'success')
}

// Replace the LIVE board with a saved slot's pages, then adopt it as the persisted active
// board and refetch. Ids come straight from the stored snapshot (a fresh deep copy), so the
// counters must resume past them; a stale activePageId falls back to the first page.
function loadSavedDashboard(id: number): void {
  const snap = loadDashboard(id)
  if (!snap || snap.pages.length === 0) return
  clearAllTileState()
  pages.value = snap.pages
  activePageId.value = snap.pages.some((p) => p.id === snap.activePageId)
    ? snap.activePageId
    : snap.pages[0].id
  resetCountersFromPages()
  for (const p of pages.value) reconcilePageLayout(p)
  crossFilter.value = null
  savedOpen.value = false
  persistNow() // the loaded board becomes the live, auto-persisted board
  loadAll()
  const loaded = dashboards.value.find((d) => d.id === id)
  pushToast('Loaded "' + (loaded?.name ?? 'dashboard') + '"', 'success')
}

function startRenameSaved(id: number, name: string): void {
  renamingSavedId.value = id
  savedNameDraft.value = name
}
function confirmRenameSaved(): void {
  if (renamingSavedId.value) renameDashboard(renamingSavedId.value, savedNameDraft.value)
  renamingSavedId.value = null
}

// Delete a named slot and confirm with a toast (Batch 9 — consistent action feedback,
// matching the toast the app shows for transforms, logins and uploads).
function removeSaved(d: { id: number; name: string }): void {
  deleteDashboard(d.id)
  pushToast('Deleted "' + d.name + '"', 'info')
}

// --- #29 Data storytelling --------------------------------------------------------
// A plain-prose overview of the whole dataset (schema-only, cached per schema_version
// server-side). On-demand: the user clicks "Tell the story". Cleared on a session switch
// or after a transform, since the previous narrative may no longer describe the data.
async function tellStory(): Promise<void> {
  const uuid = sessionUuid.value
  if (!uuid || narrating.value) return
  narrating.value = true
  storyError.value = null
  try {
    const res = await narrateDataset(uuid)
    if (uuid !== sessionUuid.value) return // session switched mid-flight -> drop
    story.value = res.narrative
  } catch (e) {
    if (uuid === sessionUuid.value) storyError.value = apiErrorMessage(e)
  } finally {
    if (uuid === sessionUuid.value) narrating.value = false
  }
}

// --- #17 export + present -----------------------------------------------------------
// Whole-dashboard PNG/PDF via html-to-image (serialises the DOM into an SVG foreignObject,
// so the BROWSER paints it -- oklch design tokens and each ChartTile's <canvas> come
// through, unlike html2canvas). Editing chrome (header actions, pickers, add-buttons, page
// tabs, drag grips) is tagged `js-export-exclude` and dropped from the capture; the same
// class is hidden in present mode via the scoped `.dashboard-clean` rule, so both views show
// one clean board (the active page only).
const captureEl = ref<HTMLElement | null>(null)
const presenting = ref(false)
const exporting = ref<'' | 'png' | 'pdf'>('')
const exportError = ref<string | null>(null)

const hasTiles = computed(
  () => (activePage.value?.kpis.length ?? 0) > 0 || (activePage.value?.charts.length ?? 0) > 0,
)

// A datestamped, filesystem-safe download name. Runs in the browser, so Date is available.
function exportName(ext: string): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `spencer-dashboard-${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}.${ext}`
}

// Walk up from the capture root to the first element with a real (non-transparent)
// background, so the PNG isn't painted on a transparent (=> black in a PDF) canvas.
function resolveBg(el: HTMLElement): string {
  let node: HTMLElement | null = el
  while (node) {
    const bg = getComputedStyle(node).backgroundColor
    if (bg && bg !== 'transparent' && !bg.startsWith('rgba(0, 0, 0, 0')) return bg
    node = node.parentElement
  }
  return '#ffffff'
}

function triggerDownload(href: string, name: string): void {
  const a = document.createElement('a')
  a.href = href
  a.download = name
  a.click()
}

// Rasterise the board (minus `js-export-exclude` chrome and the grid resize handles) to a
// PNG data URL.
const EXPORT_TIMEOUT_MS = 20000
function snapshot(el: HTMLElement): Promise<string> {
  // skipFonts: the browser that paints html-to-image's <foreignObject> already has the page fonts
  // loaded, so on-screen fidelity holds without re-embedding them — and it drops the web-font
  // inlining step (a cross-origin @font-face CSS/font fetch) that can stall the whole rasterise.
  // The timeout race then guarantees a hung rasterise *rejects* (→ error strip) instead of leaving
  // the UI wedged with `exporting` stuck truthy.
  const raster = toPng(el, {
    pixelRatio: 2,
    cacheBust: true,
    skipFonts: true,
    backgroundColor: resolveBg(el),
    filter: (node) =>
      !(
        node instanceof HTMLElement &&
        (node.classList?.contains('js-export-exclude') ||
          node.classList?.contains('vgl-item__resizer'))
      ),
  })
  const timeout = new Promise<string>((_, reject) =>
    setTimeout(
      () => reject(new Error('Export timed out — the dashboard may be too large or a resource failed to load.')),
      EXPORT_TIMEOUT_MS,
    ),
  )
  return Promise.race([raster, timeout])
}

async function exportImage(kind: 'png' | 'pdf'): Promise<void> {
  const el = captureEl.value
  if (!el || !hasTiles.value || exporting.value) return
  exporting.value = kind
  exportError.value = null
  try {
    const dataUrl = await snapshot(el)
    if (kind === 'png') {
      triggerDownload(dataUrl, exportName('png'))
      return
    }
    // PDF: a single page sized to the captured image, so the board fills it 1:1.
    const img = new Image()
    img.src = dataUrl
    await img.decode()
    const w = img.naturalWidth
    const h = img.naturalHeight
    const pdf = new jsPDF({ orientation: w >= h ? 'landscape' : 'portrait', unit: 'px', format: [w, h] })
    pdf.addImage(dataUrl, 'PNG', 0, 0, w, h)
    pdf.save(exportName('pdf'))
  } catch (e) {
    exportError.value = e instanceof Error ? e.message : 'Export failed.'
  } finally {
    exporting.value = ''
  }
}

// Present mode = fullscreen on the board with editing chrome hidden (see `.dashboard-clean`).
// Only the active page shows; drag/resize are disabled (:is-draggable/:is-resizable flip off).
// Esc exits via the browser; `fullscreenchange` keeps `presenting` in sync either way.
async function togglePresent(): Promise<void> {
  const el = captureEl.value
  if (!el) return
  try {
    if (document.fullscreenElement) await document.exitFullscreen()
    else await el.requestFullscreen()
  } catch {
    exportError.value = 'Fullscreen is not available in this browser.'
  }
}
function syncPresenting(): void {
  presenting.value = document.fullscreenElement === captureEl.value
}
onMounted(() => document.addEventListener('fullscreenchange', syncPresenting))
// #23: arriving from the Query Engine's "Send to Canvas" — the result was just
// materialized and made the active table, so drop in a fresh chart tile to configure
// over it. Read-and-clear (takePendingSeed) so it fires once, not on every keep-alive
// show; addChart no-ops if the active page is already at MAX_CHARTS.
onActivated(() => {
  if (takePendingSeed()) addChart()
})
onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', syncPresenting)
  if (persistTimer) clearTimeout(persistTimer)
})
</script>

<template>
  <div
    ref="captureEl"
    class="space-y-3"
    :class="{ 'dashboard-clean overflow-auto bg-surface-base p-4': presenting }"
  >
    <!-- Dashboard header -->
    <div class="flex items-center justify-between gap-3">
      <div class="min-w-0">
        <h2 class="flex items-center gap-1.5 text-sm font-semibold text-ink-gray-8">
          <LayoutDashboard class="h-4 w-4 text-primary" /> Dashboard
        </h2>
        <p class="mt-0.5 text-xs text-ink-gray-5">
          Live over all {{ rowCount.toLocaleString() }} rows — aggregated server-side.
        </p>
      </div>
      <div class="flex items-center gap-3 js-export-exclude">
        <!-- #15 named Save/Load slots -->
        <button
          type="button"
          class="btn btn-ghost"
          title="Save or load a named dashboard"
          @click="toggleSaved"
        >
          <BookMarked class="h-3.5 w-3.5" />
          Saved
        </button>
        <!-- #29 data storytelling: a plain-English overview of the whole dataset. -->
        <button
          type="button"
          class="btn btn-primary"
          :disabled="narrating"
          title="Summarize this dataset in plain English"
          @click="tellStory()"
        >
          <Loader2 v-if="narrating" class="h-3.5 w-3.5 animate-spin" />
          <Sparkles v-else class="h-3.5 w-3.5" />
          Tell the story
        </button>
        <button
          type="button"
          class="btn btn-ghost"
          :disabled="anyLoading"
          title="Refresh all tiles"
          @click="loadAll()"
        >
          <RefreshCw class="h-3.5 w-3.5" :class="anyLoading ? 'animate-spin' : ''" />
          Refresh
        </button>
        <!-- #17 present + whole-dashboard export -->
        <button
          type="button"
          class="btn btn-ghost"
          :disabled="!hasTiles"
          title="Present the dashboard fullscreen (Esc to exit)"
          @click="togglePresent()"
        >
          <Maximize class="h-3.5 w-3.5" />
          Present
        </button>
        <button
          type="button"
          class="btn btn-ghost"
          :disabled="!hasTiles || !!exporting"
          title="Export the whole dashboard as a PNG image"
          @click="exportImage('png')"
        >
          <Loader2 v-if="exporting === 'png'" class="h-3.5 w-3.5 animate-spin" />
          <ImageDown v-else class="h-3.5 w-3.5" />
          PNG
        </button>
        <button
          type="button"
          class="btn btn-ghost"
          :disabled="!hasTiles || !!exporting"
          title="Export the whole dashboard as a PDF"
          @click="exportImage('pdf')"
        >
          <Loader2 v-if="exporting === 'pdf'" class="h-3.5 w-3.5 animate-spin" />
          <FileDown v-else class="h-3.5 w-3.5" />
          PDF
        </button>
        <!-- Global, report-level settings (Power BI–style). Opens the settings window. -->
        <button
          type="button"
          class="btn btn-ghost"
          title="Dashboard settings (number format, theme, defaults)"
          @click="showSettings = true"
        >
          <Settings class="h-3.5 w-3.5" />
          Settings
        </button>
      </div>
    </div>

    <!-- Global dashboard settings window (Power BI–style). -->
    <Transition name="modal">
      <DashboardSettingsModal
        v-if="showSettings"
        @close="showSettings = false"
        @apply-all="applyAllToTiles"
      />
    </Transition>

    <!-- #15 Save/Load popover (ResultsTable menuOpen + fixed-backdrop idiom). -->
    <template v-if="savedOpen">
      <div class="js-export-exclude fixed inset-0 z-40" @click="savedOpen = false"></div>
      <div
        class="js-export-exclude fixed z-50 w-72 rounded-3 border border-outline-gray-2 bg-surface-base p-3 shadow-lg"
        :style="{ top: `${savedPos.y + 4}px`, left: `${savedPos.x}px`, transform: 'translateX(-100%)' }"
      >
        <p class="mb-1.5 text-[11px] font-medium text-ink-gray-6">Save current dashboard</p>
        <div class="flex gap-1.5">
          <input
            v-model="saveName"
            type="text"
            placeholder="Dashboard name"
            class="min-w-0 flex-1 rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-1 text-xs text-ink-gray-8 focus:border-primary-5 focus:outline-none"
            @keydown.enter="saveCurrentDashboard"
          />
          <button
            type="button"
            class="btn btn-primary shrink-0"
            :disabled="!saveName.trim()"
            @click="saveCurrentDashboard"
          >
            <Save class="h-3.5 w-3.5" /> Save
          </button>
        </div>
        <div class="my-2 border-t border-outline-gray-1"></div>
        <p class="mb-1 text-[11px] font-medium text-ink-gray-6">Saved dashboards</p>
        <p v-if="dashboards.length === 0" class="px-0.5 py-1 text-xs text-ink-gray-4">
          None yet — save one above.
        </p>
        <ul v-else class="max-h-56 space-y-0.5 overflow-auto">
          <li
            v-for="d in dashboards"
            :key="d.id"
            class="group/row flex items-center gap-1 rounded-2 px-1.5 py-1 hover:bg-surface-gray-2"
          >
            <input
              v-if="renamingSavedId === d.id"
              :ref="focusOnMount"
              v-model="savedNameDraft"
              type="text"
              class="min-w-0 flex-1 rounded-2 border border-outline-gray-2 bg-surface-base px-1.5 py-0.5 text-xs text-ink-gray-8 focus:border-primary-5 focus:outline-none"
              @keydown.enter="confirmRenameSaved"
              @keydown.esc="renamingSavedId = null"
              @blur="confirmRenameSaved"
            />
            <template v-else>
              <button
                type="button"
                class="min-w-0 flex-1 truncate text-left text-xs text-ink-gray-8"
                :title="`Load “${d.name}”`"
                @click="loadSavedDashboard(d.id)"
              >
                {{ d.name }}
              </button>
              <button
                type="button"
                class="shrink-0 rounded p-0.5 text-ink-gray-4 opacity-0 transition-opacity hover:text-primary group-hover/row:opacity-100"
                title="Rename"
                @click="startRenameSaved(d.id, d.name)"
              >
                <Pencil class="h-3 w-3" />
              </button>
              <button
                type="button"
                class="shrink-0 rounded p-0.5 text-ink-gray-4 opacity-0 transition-opacity hover:text-ink-red group-hover/row:opacity-100"
                title="Delete"
                @click="removeSaved(d)"
              >
                <Trash2 class="h-3 w-3" />
              </button>
            </template>
          </li>
        </ul>
      </div>
    </template>

    <!-- #17 export/present error: a rasterise or fullscreen failure surfaces here and
         never wedges the UI. Excluded from the capture itself. -->
    <div
      v-if="exportError"
      class="js-export-exclude flex items-start gap-2 rounded-3 border border-outline-red-2 bg-surface-red-1 px-3 py-2 text-xs text-ink-red"
    >
      <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span class="min-w-0 flex-1 break-words">{{ exportError }}</span>
      <button
        type="button"
        class="rounded-2 p-0.5 text-ink-red transition-colors hover:bg-surface-base"
        title="Dismiss"
        @click="exportError = null"
      >
        <X class="h-3.5 w-3.5" />
      </button>
    </div>

    <!-- #29 narrative panel: the dataset overview, above the tiles it describes. -->
    <div
      v-if="story || storyError"
      class="rounded-5 border border-primary-2 bg-primary-1/50 px-4 py-3 text-sm"
    >
      <div v-if="story" class="flex items-start gap-2">
        <Sparkles class="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <p class="min-w-0 flex-1 whitespace-pre-wrap break-words leading-relaxed text-ink-gray-8">
          {{ story }}
        </p>
        <button
          type="button"
          class="rounded-2 p-0.5 text-ink-gray-4 transition-colors hover:bg-surface-base hover:text-ink-gray-7"
          title="Dismiss"
          @click="story = null"
        >
          <X class="h-3.5 w-3.5" />
        </button>
      </div>
      <div v-else class="flex items-start gap-2 text-ink-red">
        <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
        <span class="min-w-0 flex-1 break-words">{{ storyError }}</span>
      </div>
    </div>

    <!-- Page tabs (TASK-034): named pages; click to switch, double-click or pencil to
         rename, × to delete. js-export-exclude so present/export show only the active page. -->
    <div class="js-export-exclude flex flex-wrap items-center gap-1 border-b border-outline-gray-1 pb-1.5">
      <template v-for="page in pages" :key="page.id">
        <input
          v-if="renamingPageId === page.id"
          :ref="focusOnMount"
          v-model="pageNameDraft"
          type="text"
          class="w-32 rounded-3 border border-primary-5 bg-surface-base px-2.5 py-1 text-xs text-ink-gray-9 focus:outline-none"
          @keydown.enter="confirmRenamePage"
          @keydown.esc="renamingPageId = null"
          @blur="confirmRenamePage"
        />
        <div
          v-else
          class="inline-flex cursor-pointer items-center gap-1 rounded-3 border px-2.5 py-1 text-xs transition-colors"
          :class="
            page.id === activePageId
              ? 'border-primary-3 bg-primary-1 text-ink-gray-9'
              : 'border-outline-gray-2 bg-surface-base text-ink-gray-6 hover:text-ink-gray-8'
          "
          @click="switchPage(page.id)"
          @dblclick="startRenamePage(page)"
        >
          <span class="max-w-[10rem] truncate">{{ page.name }}</span>
          <button
            v-if="page.id === activePageId"
            type="button"
            class="rounded p-0.5 text-ink-gray-4 hover:text-primary"
            title="Rename page"
            @click.stop="startRenamePage(page)"
          >
            <Pencil class="h-3 w-3" />
          </button>
          <button
            v-if="pages.length > 1"
            type="button"
            class="rounded p-0.5 text-ink-gray-4 hover:text-ink-red"
            title="Delete page"
            @click.stop="deletePage(page.id)"
          >
            <X class="h-3 w-3" />
          </button>
        </div>
      </template>
      <button
        type="button"
        class="btn btn-dashed"
        :disabled="pages.length >= MAX_PAGES"
        title="Add a page"
        @click="addPage()"
      >
        <Plus class="h-3.5 w-3.5" /> Page
      </button>
    </div>

    <!-- Active cross-filter chip: a bar/slice click filters the whole dashboard; this
         shows what's applied and clears it. -->
    <div
      v-if="crossFilter"
      class="flex items-center gap-2 rounded-3 border border-primary-2 bg-primary-1 px-3 py-1.5 text-xs text-ink-gray-8"
    >
      <Filter class="h-3.5 w-3.5 shrink-0 text-primary" />
      <span class="min-w-0 truncate">
        Filtered by <span class="font-semibold">{{ crossFilter.column }}</span> =
        <span class="font-semibold">{{ displayKey(crossFilter.value) }}</span>
      </span>
      <button
        type="button"
        class="ml-1 inline-flex shrink-0 items-center gap-1 rounded-2 px-1.5 py-0.5 text-ink-gray-6 transition-colors hover:bg-surface-base hover:text-ink-gray-8"
        title="Clear cross-filter"
        @click="clearCrossFilter()"
      >
        <X class="h-3.5 w-3.5" /> Clear
      </button>
    </div>

    <!-- The unified grid: KPI cards + charts share one movable/resizable surface. TASK-036:
         the WHOLE card is the drag handle (`.tile-drag-handle` on each tile root), so you can
         grab a tile anywhere to move it (Power BI feel); `drag-ignore-from` keeps every
         button / select / input / plot canvas / popover / resize handle live. Each tile fills
         its GridItem (h-full); ChartTile's useEchart ResizeObserver re-renders on resize. -->
    <GridLayout
      v-if="activePage && layout.length > 0"
      :layout="layout"
      :col-num="GRID_COLS"
      :row-height="GRID_ROW_HEIGHT"
      :margin="GRID_MARGIN"
      :is-draggable="!presenting"
      :is-resizable="!presenting"
      :vertical-compact="true"
      :use-css-transforms="true"
      @layout-updated="onLayoutUpdated"
    >
      <GridItem
        v-for="(item, idx) in layout"
        :key="item.i"
        :i="item.i"
        :x="item.x"
        :y="item.y"
        :w="item.w"
        :h="item.h"
        :min-w="minWFor(item.i)"
        :min-h="minHFor(item.i)"
        drag-allow-from=".tile-drag-handle"
        drag-ignore-from="button, select, input, textarea, a, summary, canvas, .no-drag, .vgl-item__resizer"
      >
        <ErrorBoundary>
        <KpiCard
          v-if="kpiByTile(item.i)"
          class="tile-enter"
          :style="{ animationDelay: Math.min(idx, 8) * 50 + 'ms' }"
          :config="kpiByTile(item.i)!"
          :columns="columns"
          :loading="kpiStateOf(kpiByTile(item.i)!.id).loading"
          :error="kpiStateOf(kpiByTile(item.i)!.id).error"
          :value="kpiStateOf(kpiByTile(item.i)!.id).data"
          :trend="kpiTrendOf(kpiByTile(item.i)!.id).data"
          :selected="isSelected('kpi', kpiByTile(item.i)!.id)"
          @update:config="onKpiUpdate"
          @remove="onKpiRemove"
          @duplicate="onKpiDuplicate"
          @open-settings="openTileSettings('kpi', kpiByTile(item.i)!.id)"
        />
        <ChartTile
          v-else-if="chartByTile(item.i)"
          class="tile-enter"
          :style="{ animationDelay: Math.min(idx, 8) * 50 + 'ms' }"
          :config="chartByTile(item.i)!.config"
          :columns="columns"
          :loading="chartStateOf(chartByTile(item.i)!.id).loading"
          :error="chartStateOf(chartByTile(item.i)!.id).error"
          :data="chartStateOf(chartByTile(item.i)!.id).data"
          :active-key="activeKeyFor(chartByTile(item.i)!.id)"
          :selected="isSelected('chart', chartByTile(item.i)!.id)"
          @update:config="(cfg) => onChartUpdate(chartByTile(item.i)!.id, cfg)"
          @select="(key) => onChartSelect(chartByTile(item.i)!.id, key)"
          @remove="onChartRemove(chartByTile(item.i)!.id)"
          @duplicate="onChartDuplicate(chartByTile(item.i)!.id)"
          @open-settings="openTileSettings('chart', chartByTile(item.i)!.id)"
        />
        </ErrorBoundary>
      </GridItem>
    </GridLayout>

    <!-- Empty page hint: a page with no tiles (a freshly added one) prompts for the first. -->
    <EmptyState
      v-else-if="activePage"
      title="Your canvas is empty"
      subtitle="Add a KPI or a chart to start telling the story — Spencer will suggest a layout from your data."
    >
      <template #art>
        <svg
          width="76" height="56" viewBox="0 0 76 56" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
          aria-hidden="true"
        >
          <rect x="10" y="9" width="56" height="40" rx="7" />
          <path d="M20 42V32M32 42V23M44 42V29M56 42V16" />
          <circle cx="56" cy="16" r="3" fill="currentColor" stroke="none" />
        </svg>
      </template>
    </EmptyState>

    <!-- Add toolbar: append a tile to the active page (each lands at the bottom of the grid). -->
    <div class="js-export-exclude flex flex-wrap items-center gap-3">
      <button
        type="button"
        class="btn btn-dashed"
        :disabled="!activePage || kpis.length >= MAX_KPIS"
        title="Add a KPI card"
        @click="addKpi()"
      >
        <Plus class="h-4 w-4" /> Add KPI
      </button>
      <button
        type="button"
        class="btn btn-dashed"
        :disabled="!activePage || charts.length >= MAX_CHARTS"
        title="Add a chart"
        @click="addChart()"
      >
        <Plus class="h-4 w-4" /> Add chart
      </button>
    </div>
  </div>
</template>

<style scoped>
/* #17 present mode: the same js-export-exclude contract the PNG filter drops also hides
   all editing chrome in fullscreen, so the presented board matches the exported image. */
.dashboard-clean :deep(.js-export-exclude) {
  display: none !important;
}

/* grid-layout-plus: brand the drag placeholder (the library default is a solid red box).
   Uses the primary tint tokens (not a raw slate literal) so it reads on-brand. */
:deep(.vgl-item--placeholder) {
  background-color: var(--primary-2);
  border: 1px dashed var(--primary-3);
  border-radius: 12px;
  opacity: 1;
}
/* Keep the resize handle subtle until the tile is hovered. */
:deep(.vgl-item > .vgl-item__resizer) {
  opacity: 0;
  transition: opacity 0.15s ease;
}
:deep(.vgl-item:hover > .vgl-item__resizer) {
  opacity: 0.5;
}
/* Present mode: no resize affordance (drag/resize are already disabled via props). */
.dashboard-clean :deep(.vgl-item__resizer) {
  display: none !important;
}
</style>
