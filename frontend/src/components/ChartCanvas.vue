<script setup lang="ts">
// The Canvas dashboard container: the ONLY place that fetches aggregates.
//
// Tiles (KpiCard / ChartTile) are presentational + own their pickers; they emit config
// changes upward and this component re-runs the affected aggregation. Centralising the
// data layer is what makes "clean the data in the Table tab -> the whole dashboard
// refreshes" a single `dataVersion` watch instead of N independent subscriptions.
//
// Tile configuration is EPHEMERAL view state. App.vue wraps <router-view> in
// <keep-alive>, so it survives tab switches, but not a page reload -- saved dashboards
// are deliberately out of scope for Canvas v1.
import { computed, reactive, ref, watch } from 'vue'
import { AlertCircle, Filter, LayoutDashboard, Loader2, Plus, RefreshCw, Sparkles, X } from '@lucide/vue'
import type {
  AggregateFilter,
  AggregateKey,
  AggregateResponse,
  AggregateValue,
  ChartConfig,
  ColumnMeta,
  KpiConfig,
  TileState,
} from '../types'
import { supportsBreakdown } from '../types'
import { useSession } from '../composables/useSession'
import { apiErrorMessage, fetchAggregate, narrateDataset } from '../services/api'
import { categoricalColumns, numericColumns, temporalColumns } from '../utils/columnKind'
import KpiCard from './KpiCard.vue'
import ChartTile from './ChartTile.vue'

const { sessionUuid, tableName, columns, rowCount, dataVersion } = useSession()

const MAX_KPIS = 6
const MAX_CHARTS = 6
const SERIES_LIMIT = 50 // top-N categories; the server clamps to 200.
const BLANK: TileState<AggregateValue> = { loading: false, error: null, data: null }
const BLANK_CHART: TileState<AggregateResponse> = { loading: false, error: null, data: null }

const kpis = ref<KpiConfig[]>([])
const kpiState = reactive<Record<number, TileState<AggregateValue> | undefined>>({})

// A chart tile = an id + its config. ChartConfig stays id-free (it is the pure query +
// render spec); the id lives on the wrapper so tiles can be added/removed and their
// fetch state keyed independently, exactly like the KPI cards.
interface ChartEntry {
  id: number
  config: ChartConfig
}
const charts = ref<ChartEntry[]>([])
const chartStates = reactive<Record<number, TileState<AggregateResponse> | undefined>>({})

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

let nextKpiId = 1
let nextChartId = 1

// Monotonic request counters, one per tile (same guard OpDialog uses for its dry-run
// previews). A slow response from an older config must never overwrite a newer one.
const kpiSeq: Record<number, number> = {}
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

// Always replace the whole state object: mutating a freshly-inserted plain object
// would bypass the reactive proxy and the tile would not re-render.
function setKpiState(id: number, patch: Partial<TileState<AggregateValue>>): void {
  kpiState[id] = { ...(kpiState[id] ?? BLANK), ...patch }
}

// --- Auto-seed -------------------------------------------------------------------
// A dashboard should exist the instant a file lands, so the first tiles are inferred
// from the schema; every one of them is editable afterwards.
function seed(cols: ColumnMeta[]): void {
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
  kpis.value = seeded

  // Prefer a categorical column that actually groups (cardinality > 1) and stays
  // readable (<= 50 bars). `cardinality` is optional, so an unknown one is allowed
  // through rather than excluded.
  const grouping = cats.filter((c) => c.cardinality === undefined || c.cardinality > 1)
  const readable = grouping.find((c) => c.cardinality !== undefined && c.cardinality <= 50)
  const dim = readable ?? grouping[0] ?? temps[0] ?? null
  const isTemporal = dim !== null && temps.some((t) => t.name === dim.name)

  charts.value = [
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
        limit: SERIES_LIMIT,
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

// Tiles are independent: one failing aggregation must not blank the others.
function loadAll(): void {
  for (const cfg of kpis.value) void loadKpi(cfg)
  for (const entry of charts.value) void loadChart(entry)
}

// --- Reactions -------------------------------------------------------------------
// New session (or a "Replace dataset"): throw the old dashboard away and re-seed.
watch(
  sessionUuid,
  (uuid) => {
    for (const key of Object.keys(kpiState)) delete kpiState[Number(key)]
    for (const key of Object.keys(chartStates)) delete chartStates[Number(key)]
    kpis.value = []
    charts.value = []
    crossFilter.value = null
    story.value = null
    storyError.value = null
    if (!uuid) return
    seed(columns.value)
    loadAll()
  },
  { immediate: true },
)

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
  kpis.value[i] = cfg
  void loadKpi(cfg)
}

function onKpiRemove(id: number): void {
  kpis.value = kpis.value.filter((k) => k.id !== id)
  delete kpiState[id]
  delete kpiSeq[id]
}

function addKpi(): void {
  if (kpis.value.length >= MAX_KPIS) return
  // Start from COUNT(*): always valid whatever the schema looks like.
  const cfg: KpiConfig = { id: nextKpiId++, measure: null, aggregation: 'count' }
  kpis.value = [...kpis.value, cfg]
  void loadKpi(cfg)
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
    effectiveSeries(prev) === effectiveSeries(cfg)
  if (!sameQuery || chartStateOf(id).data === null) void loadChart(charts.value[i])
}

function onChartRemove(id: number): void {
  charts.value = charts.value.filter((c) => c.id !== id)
  delete chartStates[id]
  delete chartSeq[id]
  // Removing the tile that owns the cross-filter clears it and un-filters the rest.
  if (crossFilter.value?.sourceId === id) {
    crossFilter.value = null
    loadAll()
  }
}

function addChart(): void {
  if (charts.value.length >= MAX_CHARTS) return
  // Start blank (no dimension) -> the tile shows its "choose a dimension" prompt.
  const entry: ChartEntry = {
    id: nextChartId++,
    config: { dimension: null, series: null, measure: null, aggregation: 'count', chartType: 'bar' },
  }
  charts.value = [...charts.value, entry]
  void loadChart(entry)
}

// --- Cross-filter ----------------------------------------------------------------
// A bar/slice click on a chart tile. Set the slice, or toggle it OFF when the same key
// on the same tile is clicked again, then refetch everything: KPIs + other charts filter
// down while the source tile stays whole with the clicked category highlighted.
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
</script>

<template>
  <div class="space-y-4">
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
      <div class="flex items-center gap-2">
        <!-- #29 data storytelling: a plain-English overview of the whole dataset. -->
        <button
          type="button"
          class="flex items-center gap-1.5 rounded-3 bg-primary px-2.5 py-1.5 text-xs font-medium text-ink-white shadow-sm transition-colors hover:bg-primary-7 disabled:cursor-not-allowed disabled:opacity-50"
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
          class="flex items-center gap-1.5 rounded-3 border border-outline-gray-2 bg-surface-base px-2.5 py-1.5 text-xs text-ink-gray-7 transition-colors hover:bg-surface-gray-2 disabled:opacity-50"
          :disabled="anyLoading"
          title="Refresh all tiles"
          @click="loadAll()"
        >
          <RefreshCw class="h-3.5 w-3.5" :class="anyLoading ? 'animate-spin' : ''" />
          Refresh
        </button>
      </div>
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

    <!-- KPI row -->
    <div class="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <KpiCard
        v-for="k in kpis"
        :key="k.id"
        :config="k"
        :columns="columns"
        :loading="kpiStateOf(k.id).loading"
        :error="kpiStateOf(k.id).error"
        :value="kpiStateOf(k.id).data"
        @update:config="onKpiUpdate"
        @remove="onKpiRemove"
      />
      <button
        v-if="kpis.length < MAX_KPIS"
        type="button"
        class="flex min-h-[6rem] flex-col items-center justify-center gap-1 rounded-5 border border-dashed border-outline-gray-3 text-xs text-ink-gray-5 transition-colors hover:border-primary-5 hover:text-primary"
        @click="addKpi()"
      >
        <Plus class="h-4 w-4" />
        Add KPI
      </button>
    </div>

    <!-- Chart tiles: a real dashboard has several. Each owns its pickers and can be
         removed; ChartCanvas still owns all fetching, so one dataVersion watch refreshes
         every tile with its existing config. -->
    <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <ChartTile
        v-for="c in charts"
        :key="c.id"
        :config="c.config"
        :columns="columns"
        :loading="chartStateOf(c.id).loading"
        :error="chartStateOf(c.id).error"
        :data="chartStateOf(c.id).data"
        :active-key="activeKeyFor(c.id)"
        @update:config="(cfg) => onChartUpdate(c.id, cfg)"
        @select="(key) => onChartSelect(c.id, key)"
        @remove="onChartRemove(c.id)"
      />
      <button
        v-if="charts.length < MAX_CHARTS"
        type="button"
        class="flex min-h-[240px] flex-col items-center justify-center gap-1 rounded-5 border border-dashed border-outline-gray-3 text-xs text-ink-gray-5 transition-colors hover:border-primary-5 hover:text-primary"
        @click="addChart()"
      >
        <Plus class="h-5 w-5" />
        Add chart
      </button>
    </div>
  </div>
</template>
