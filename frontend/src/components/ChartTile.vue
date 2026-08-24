<script setup lang="ts">
// The configurable chart tile. Owns its field pickers and its ECharts option, but no
// aggregation fetching: it emits `update:config` and ChartCanvas re-runs the aggregation.
// Keeping data orchestration in the container is what lets one dataVersion watch refresh
// every tile with its existing config.
//
// Exception (Wave 4): two ON-DEMAND AI helpers live here because they are about THIS
// tile's own config/data and never feed the reactive aggregation pipeline — #18 "Explain
// this chart" (narrate the series already in hand) and #30 "Recommend a chart type"
// (suggest + apply a chartType for the current dimension). Both are one-shot request →
// display; neither participates in dataVersion refresh.
import { computed, ref } from 'vue'
import { AlertCircle, BarChart3, Download, Lightbulb, Loader2, Sparkles, X } from '@lucide/vue'
import type { EChartsCoreOption } from 'echarts/core'
import type {
  AggregateKey,
  AggregateResponse,
  AggregateValue,
  Aggregation,
  ChartConfig,
  ChartType,
  ColumnMeta,
  ExplainChartRequest,
} from '../types'
import { supportsBreakdown } from '../types'
import { useSession } from '../composables/useSession'
import { apiErrorMessage, explainChart, recommendChart } from '../services/api'
import { useEchart } from '../composables/useEchart'
import { AGG_LABEL, allowedAggregations, coerceAggregation } from '../utils/aggregations'
import { dimensionColumns } from '../utils/columnKind'
import {
  CHART_FONT,
  CHART_INK,
  CHART_PRIMARY,
  CHART_SPLIT_LINE,
  paletteColor,
} from '../utils/chartPalette'

const props = defineProps<{
  config: ChartConfig
  columns: ColumnMeta[]
  loading: boolean
  error: string | null
  data: AggregateResponse | null
  // Set only on the tile that OWNS the active cross-filter: the selected key, so its
  // bar/slice stays lit while the rest dim. `undefined` => this tile isn't the source.
  activeKey?: AggregateKey
}>()

const emit = defineEmits<{
  'update:config': [config: ChartConfig]
  remove: []
  // A bar/slice was clicked: the raw dimension key, for ChartCanvas to cross-filter on.
  select: [key: AggregateKey]
}>()

const { sessionUuid } = useSession()

const chartEl = ref<HTMLElement | null>(null)

const CHART_TYPES: { value: ChartType; label: string }[] = [
  { value: 'bar', label: 'Bar' },
  { value: 'line', label: 'Line' },
  { value: 'area', label: 'Area' },
  { value: 'hbar', label: 'Horizontal bar' },
  { value: 'pie', label: 'Pie' },
  { value: 'stacked', label: 'Stacked bar' },
  { value: 'heatmap', label: 'Heatmap' },
  { value: 'treemap', label: 'Treemap' },
  { value: 'funnel', label: 'Funnel' },
]
// Chart types that draw one sub-series per breakdown value (2-D). The Breakdown picker
// shows only for these; the others ignore `config.series` (ChartCanvas drops it from the
// request too, so a stale series never corrupts a 1-D shape). `heatmap` REQUIRES one.
const CROSS_FILTER_TYPES: ReadonlySet<ChartType> = new Set([
  'bar', 'line', 'area', 'hbar', 'stacked', 'pie',
])
// The chart types the backend #30 recommender is constrained to; used to validate its
// string reply before we ever apply it (fail-safe: an unknown value is ignored).
const CHART_TYPE_LABEL: Record<string, string> = Object.fromEntries(
  CHART_TYPES.map((t) => [t.value, t.label]),
)
function isChartType(v: string): v is ChartType {
  return v in CHART_TYPE_LABEL
}
function typeLabel(v: string): string {
  return CHART_TYPE_LABEL[v] ?? v
}

const dimOptions = computed(() => dimensionColumns(props.columns))
const aggOptions = computed(() => allowedAggregations(props.columns, props.config.measure))

// Breakdown picker: shown only for the 2-D-capable types, and never offers the column
// already used as the primary dimension (that would be a redundant self-split).
const showBreakdown = computed(() => supportsBreakdown(props.config.chartType))
const seriesOptions = computed(() =>
  dimOptions.value.filter((c) => c.name !== props.config.dimension),
)

const measureLabel = computed(() =>
  props.config.measure === null
    ? 'Count of rows'
    : `${AGG_LABEL[props.config.aggregation]} of ${props.config.measure}`,
)

// A 2-D result actually arrived: the type supports a breakdown, one is set, and the
// backend returned a non-empty matrix + series axis. Everything that plots 2-D gates on
// this; when false the tile falls back to (or stays on) its 1-D shape.
const is2D = computed(() => {
  const d = props.data
  return (
    showBreakdown.value &&
    props.config.series !== null &&
    !!d &&
    (d.series_keys?.length ?? 0) > 0 &&
    (d.matrix?.length ?? 0) > 0
  )
})

const title = computed(() => {
  const base = props.config.dimension
    ? `${measureLabel.value} by ${props.config.dimension}`
    : measureLabel.value
  return is2D.value && props.config.series ? `${base}, split by ${props.config.series}` : base
})

// A transform may have dropped or renamed a charted column since this tile was built.
const missingColumn = computed(() => {
  const names = props.columns.map((c) => c.name)
  const { dimension, measure, series } = props.config
  return (
    (dimension !== null && !names.includes(dimension)) ||
    (measure !== null && !names.includes(measure)) ||
    (showBreakdown.value && series !== null && !names.includes(series))
  )
})

const hasData = computed(() => (props.data?.keys.length ?? 0) > 0)

// When the tile has data in hand but the chosen type can't draw it yet (a heatmap with
// no breakdown selected), guide the user instead of leaving a blank canvas.
const plotHint = computed<string | null>(() => {
  if (props.config.chartType !== 'heatmap') return null
  if (!hasData.value) return null // the standard empty-state overlay covers this
  if (props.config.series === null) return 'Pick a breakdown column to build the heatmap.'
  if (!is2D.value) return 'No data for this dimension × breakdown combination.'
  return null
})

/** ISO strings (MIN/MAX over a date) are not plottable — drop them to null rather
 *  than letting NaN through and blanking the axis. */
function toNumber(v: AggregateValue): number | null {
  if (v === null) return null
  if (typeof v === 'number') return Number.isFinite(v) ? v : null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

const axisLabelStyle = { color: CHART_INK, fontFamily: CHART_FONT, fontSize: 11 }

// Cross-filter highlight: when this tile owns the active slice, the selected key stays
// fully opaque and every other bar/slice dims. `activeKey === undefined` (not the source
// tile) leaves everything at full opacity — the common, unfiltered case.
function itemOpacity(key: AggregateKey): number {
  return props.activeKey === undefined || key === props.activeKey ? 1 : 0.35
}

const option = computed<EChartsCoreOption | null>(() => {
  const d = props.data
  if (!d) return null
  const t = props.config.chartType

  // Category-axis chrome, shared by every cartesian shape (1-D, 2-D and heatmap).
  // `flat` suppresses the >8-entry label rotation (a horizontal bar reads labels flat).
  const makeCategoryAxis = (labels: string[], flat = false) => ({
    type: 'category' as const,
    data: labels,
    axisLabel: {
      ...axisLabelStyle,
      rotate: !flat && labels.length > 8 ? 35 : 0,
      hideOverlap: true,
    },
    axisTick: { show: false },
    axisLine: { lineStyle: { color: CHART_SPLIT_LINE } },
  })
  const valueAxis = {
    type: 'value' as const,
    axisLabel: axisLabelStyle,
    axisLine: { show: false },
    splitLine: { lineStyle: { color: CHART_SPLIT_LINE } },
  }

  // ---- 2-D breakdown shapes (dimension × series → matrix) --------------------------
  if (is2D.value) {
    const xlabels = d.keys.map((k) => (k === null ? '(null)' : String(k)))
    const slabels = (d.series_keys ?? []).map((s) => (s === null ? '(null)' : String(s)))
    const matrix = d.matrix ?? []

    if (t === 'heatmap') {
      // ECharts heatmap wants [xIndex, yIndex, value] triples; skip empty cells so a
      // gap stays uncoloured rather than reading as a zero.
      const cells: [number, number, number][] = []
      let vmin = Infinity
      let vmax = -Infinity
      matrix.forEach((row, i) =>
        row.forEach((raw, j) => {
          const n = toNumber(raw)
          if (n === null) return
          cells.push([i, j, n])
          if (n < vmin) vmin = n
          if (n > vmax) vmax = n
        }),
      )
      if (!Number.isFinite(vmin)) {
        vmin = 0
        vmax = 0
      }
      return {
        tooltip: {
          position: 'top',
          formatter: (p: { value: [number, number, number] }) =>
            `${xlabels[p.value[0]]} · ${slabels[p.value[1]]}: ${p.value[2]}`,
        },
        grid: {
          left: 4,
          right: 16,
          top: 12,
          bottom: 56,
          outerBoundsMode: 'same',
          outerBoundsContain: 'axisLabel',
        },
        xAxis: { ...makeCategoryAxis(xlabels), splitArea: { show: true } },
        yAxis: {
          type: 'category' as const,
          data: slabels,
          axisLabel: axisLabelStyle,
          axisTick: { show: false },
          axisLine: { lineStyle: { color: CHART_SPLIT_LINE } },
          splitArea: { show: true },
        },
        visualMap: {
          min: vmin,
          max: vmax,
          calculable: true,
          orient: 'horizontal',
          left: 'center',
          bottom: 8,
          itemWidth: 14,
          textStyle: axisLabelStyle,
          inRange: { color: ['oklch(0.945 0.03 252)', CHART_PRIMARY] },
        },
        series: [
          {
            type: 'heatmap',
            name: measureLabel.value,
            data: cells,
            label: { show: false },
            itemStyle: { borderColor: 'oklch(1 0 0)', borderWidth: 1 },
          },
        ],
      }
    }

    // Multi-series cartesian: grouped bar / stacked bar / multi-line / stacked area.
    // One series per breakdown value, each a column of the matrix. `area` and `stacked`
    // stack onto one total; `bar` groups side-by-side; `line` overlays.
    const isBar = t === 'bar' || t === 'stacked'
    const stack = t === 'stacked' || t === 'area' ? 'total' : undefined
    const series = slabels.map((name, j) => ({
      type: (isBar ? 'bar' : 'line') as 'bar' | 'line',
      name,
      stack,
      data: matrix.map((row) => toNumber(row[j])),
      barMaxWidth: 48,
      itemStyle: { color: paletteColor(j) },
      lineStyle: isBar ? undefined : { width: 2, color: paletteColor(j) },
      areaStyle: t === 'area' ? { opacity: 0.2, color: paletteColor(j) } : undefined,
      smooth: !isBar,
      symbolSize: 6,
    }))
    return {
      grid: {
        left: 4,
        right: 16,
        top: 34,
        bottom: 4,
        outerBoundsMode: 'same',
        outerBoundsContain: 'axisLabel',
      },
      tooltip: { trigger: 'axis', axisPointer: { type: isBar ? 'shadow' : 'line' } },
      legend: { type: 'scroll', top: 4, textStyle: axisLabelStyle },
      xAxis: makeCategoryAxis(xlabels),
      yAxis: valueAxis,
      series,
    }
  }

  // ---- 1-D shapes ------------------------------------------------------------------
  if (d.keys.length === 0) return null
  // A heatmap needs the 2-D matrix; without a breakdown there is nothing to draw (the
  // plotHint overlay tells the user to pick one). Returning null keeps a stale line/bar
  // from flashing behind that hint.
  if (t === 'heatmap') return null

  const labels = d.keys.map((k) => (k === null ? '(null)' : String(k)))
  const values = d.values.map(toNumber)

  if (t === 'pie') {
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: {
        type: 'scroll',
        orient: 'vertical',
        right: 8,
        top: 'middle',
        textStyle: axisLabelStyle,
      },
      series: [
        {
          type: 'pie',
          name: measureLabel.value,
          radius: ['45%', '72%'],
          center: ['36%', '50%'],
          label: { show: false },
          itemStyle: { borderColor: 'oklch(1 0 0)', borderWidth: 2 },
          data: labels.map((name, i) => ({
            name,
            value: values[i] ?? 0,
            itemStyle: { color: paletteColor(i), opacity: itemOpacity(d.keys[i]) },
          })),
        },
      ],
    }
  }

  if (t === 'treemap') {
    // Nested-rectangle alternative to pie: area ∝ value. Zoom/breadcrumb off — a tile is
    // a single flat level, and clicks are reserved for (future) cross-filtering, not drill.
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c}' },
      series: [
        {
          type: 'treemap',
          name: measureLabel.value,
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          label: { show: true, formatter: '{b}', color: 'oklch(1 0 0)', fontFamily: CHART_FONT },
          itemStyle: { borderColor: 'oklch(1 0 0)', borderWidth: 2, gapWidth: 2 },
          data: labels.map((name, i) => ({
            name,
            value: values[i] ?? 0,
            itemStyle: { color: paletteColor(i), opacity: itemOpacity(d.keys[i]) },
          })),
        },
      ],
    }
  }

  if (t === 'funnel') {
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c}' },
      legend: { type: 'scroll', bottom: 0, textStyle: axisLabelStyle },
      series: [
        {
          type: 'funnel',
          name: measureLabel.value,
          top: 12,
          bottom: 32,
          left: '8%',
          right: '8%',
          minSize: '2%',
          sort: 'descending',
          gap: 2,
          label: {
            show: true,
            position: 'inside',
            color: 'oklch(1 0 0)',
            fontFamily: CHART_FONT,
            fontSize: 11,
          },
          labelLine: { show: false },
          itemStyle: { borderColor: 'oklch(1 0 0)', borderWidth: 1 },
          data: labels.map((name, i) => ({
            name,
            value: values[i] ?? 0,
            itemStyle: { color: paletteColor(i), opacity: itemOpacity(d.keys[i]) },
          })),
        },
      ],
    }
  }

  // bar / line / area / hbar share one cartesian frame; `stacked` with no breakdown
  // degrades to a plain bar. Only the series type, orientation and fill differ. `hbar`
  // swaps the category axis onto Y.
  const isHorizontal = t === 'hbar'
  const isBarSeries = t === 'bar' || t === 'hbar' || t === 'stacked'
  const isArea = t === 'area'

  const categoryAxis = makeCategoryAxis(labels, isHorizontal)

  // Per-bar opacity only when this tile owns the cross-filter (and only for bar/hbar —
  // a line/area with a single bright point would read as broken). Otherwise the series
  // takes the plain number array, keeping the unfiltered path allocation-free.
  const seriesData =
    props.activeKey !== undefined && isBarSeries
      ? values.map((v, i) => ({ value: v, itemStyle: { opacity: itemOpacity(d.keys[i]) } }))
      : values

  return {
    // ECharts 6 deprecated `grid.containLabel`; without registering the legacy feature it
    // is silently ignored and rotated axis labels get clipped. `outerBoundsMode: 'same'`
    // + `outerBoundsContain: 'axisLabel'` is its documented equivalent, and needs no extra
    // module in the modular build.
    grid: {
      left: 4,
      right: 16,
      top: 16,
      bottom: 4,
      outerBoundsMode: 'same',
      outerBoundsContain: 'axisLabel',
    },
    tooltip: { trigger: 'axis', axisPointer: { type: isBarSeries ? 'shadow' : 'line' } },
    xAxis: isHorizontal ? valueAxis : categoryAxis,
    yAxis: isHorizontal ? categoryAxis : valueAxis,
    series: [
      {
        type: isBarSeries ? 'bar' : 'line',
        name: measureLabel.value,
        data: seriesData,
        barMaxWidth: 48,
        itemStyle: {
          color: CHART_PRIMARY,
          borderRadius: isBarSeries ? (isHorizontal ? [0, 3, 3, 0] : [3, 3, 0, 0]) : 0,
        },
        lineStyle: isBarSeries ? undefined : { width: 2, color: CHART_PRIMARY },
        areaStyle: isArea ? { opacity: 0.15, color: CHART_PRIMARY } : undefined,
        symbolSize: 6,
        smooth: !isBarSeries,
      },
    ],
  }
})

// Map an ECharts click (reported by data index) back to the raw dimension key and bubble
// it up; ChartCanvas turns it into a cross-filter. Only the types whose dataIndex indexes
// the primary keys[] participate (a heatmap cell / treemap tile / funnel stage does not).
function onSliceClick(dataIndex: number): void {
  if (!CROSS_FILTER_TYPES.has(props.config.chartType)) return
  const d = props.data
  if (!d || dataIndex < 0 || dataIndex >= d.keys.length) return
  emit('select', d.keys[dataIndex])
}

const echart = useEchart(chartEl, option, onSliceClick)

// Export the current chart as a PNG via ECharts' own canvas snapshot. Pure client-side
// (no server round trip); disabled while there is nothing plotted.
function exportPng(): void {
  if (typeof document === 'undefined') return
  const url = echart.getDataURL()
  if (!url) return
  const safe = title.value.replace(/[^\w.-]+/g, '_').slice(0, 60) || 'chart'
  const a = document.createElement('a')
  a.href = url
  a.download = `${safe}.png`
  a.click()
}

function onDimensionChange(raw: string): void {
  const dimension = raw === '' ? null : raw
  // Drop a breakdown that just became the primary dimension (no self-split).
  const series = props.config.series === dimension ? null : props.config.series
  emit('update:config', { ...props.config, dimension, series })
}

function onSeriesChange(raw: string): void {
  emit('update:config', { ...props.config, series: raw === '' ? null : raw })
}

function onMeasureChange(raw: string): void {
  const measure = raw === '' ? null : raw
  emit('update:config', {
    ...props.config,
    measure,
    aggregation: coerceAggregation(props.columns, measure, props.config.aggregation),
  })
}

function onAggChange(raw: string): void {
  emit('update:config', { ...props.config, aggregation: raw as Aggregation })
}

function onTypeChange(raw: string): void {
  emit('update:config', { ...props.config, chartType: raw as ChartType })
}

// Apply a chart type coming from the #30 recommender (or one of its alternative chips).
// No-op if it is already the current type, so re-applying a suggestion is free.
function applyType(t: ChartType): void {
  if (t !== props.config.chartType) emit('update:config', { ...props.config, chartType: t })
}

// --- #18 Explain this chart -------------------------------------------------------
// Narrate the series the tile already holds — no new query. The uuid-staleness guard
// mirrors the fetch paths: a session switch mid-flight drops the late reply.
const explaining = ref(false)
const explainText = ref<string | null>(null)
const explainError = ref<string | null>(null)

async function explainThisChart(): Promise<void> {
  const uuid = sessionUuid.value
  const d = props.data
  if (!uuid || !d || !hasData.value || explaining.value) return
  explaining.value = true
  explainError.value = null
  explainText.value = null
  const spec: ExplainChartRequest = {
    title: title.value,
    chart_type: props.config.chartType,
    dimension: props.config.dimension,
    measure: props.config.measure,
    aggregation: props.config.aggregation,
    keys: d.keys,
    values: d.values,
  }
  try {
    const res = await explainChart(uuid, spec)
    if (uuid !== sessionUuid.value) return
    explainText.value = res.narrative
  } catch (e) {
    if (uuid === sessionUuid.value) explainError.value = apiErrorMessage(e)
  } finally {
    if (uuid === sessionUuid.value) explaining.value = false
  }
}

// --- #30 Recommend a chart type ---------------------------------------------------
// Suggest a chartType for the current dimension, then APPLY it (chart type is a pure,
// instantly-reversible render change — the Type dropdown is right there). The panel keeps
// the model's reasoning + any alternatives as one-click chips.
const recommending = ref(false)
const recommendError = ref<string | null>(null)
const recommendPanel = ref<{ chartType: string; reasoning: string; alternatives: ChartType[] } | null>(
  null,
)

async function recommend(): Promise<void> {
  const uuid = sessionUuid.value
  const dim = props.config.dimension
  if (!uuid || !dim || recommending.value) return
  recommending.value = true
  recommendError.value = null
  const dimType = props.columns.find((c) => c.name === dim)?.type ?? null
  try {
    const res = await recommendChart(uuid, dim, dimType, title.value)
    if (uuid !== sessionUuid.value) return
    // Keep only alternatives we can actually render, and never echo the primary pick.
    const alts = res.alternatives.filter(
      (a): a is ChartType => isChartType(a) && a !== res.chart_type,
    )
    recommendPanel.value = { chartType: res.chart_type, reasoning: res.reasoning, alternatives: alts }
    if (isChartType(res.chart_type)) applyType(res.chart_type)
  } catch (e) {
    if (uuid === sessionUuid.value) recommendError.value = apiErrorMessage(e)
  } finally {
    if (uuid === sessionUuid.value) recommending.value = false
  }
}

const selectCls =
  'rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-1 text-xs text-ink-gray-8 focus:border-primary-5 focus:outline-none'
const labelCls = 'mb-1 block text-[11px] font-medium text-ink-gray-6'
</script>

<template>
  <div class="flex flex-col overflow-hidden rounded-5 border border-outline-gray-1 bg-surface-base shadow-sm">
    <!-- Header -->
    <div class="flex flex-wrap items-end justify-between gap-3 border-b border-outline-gray-1 bg-surface-gray-1 px-4 py-3">
      <h3 class="flex min-w-0 items-center gap-1.5 text-sm font-semibold text-ink-gray-8">
        <BarChart3 class="h-4 w-4 shrink-0 text-primary" />
        <span class="truncate" :title="title">{{ title }}</span>
      </h3>

      <div class="flex flex-wrap items-end gap-2">
        <div>
          <label :class="labelCls">Dimension</label>
          <select
            :class="selectCls"
            :value="config.dimension ?? ''"
            @change="onDimensionChange(($event.target as HTMLSelectElement).value)"
          >
            <option value="">— none —</option>
            <option v-for="c in dimOptions" :key="c.name" :value="c.name">{{ c.name }}</option>
          </select>
        </div>
        <div v-if="showBreakdown">
          <label :class="labelCls">Breakdown</label>
          <select
            :class="selectCls"
            :value="config.series ?? ''"
            :disabled="!config.dimension"
            @change="onSeriesChange(($event.target as HTMLSelectElement).value)"
          >
            <option value="">— none —</option>
            <option v-for="c in seriesOptions" :key="c.name" :value="c.name">{{ c.name }}</option>
          </select>
        </div>
        <div>
          <label :class="labelCls">Measure</label>
          <select
            :class="selectCls"
            :value="config.measure ?? ''"
            @change="onMeasureChange(($event.target as HTMLSelectElement).value)"
          >
            <option value="">Count of rows</option>
            <option v-for="c in columns" :key="c.name" :value="c.name">{{ c.name }}</option>
          </select>
        </div>
        <div v-if="config.measure !== null">
          <label :class="labelCls">Aggregation</label>
          <select
            :class="selectCls"
            :value="config.aggregation"
            @change="onAggChange(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="a in aggOptions" :key="a" :value="a">{{ AGG_LABEL[a] }}</option>
          </select>
        </div>
        <div>
          <label :class="labelCls">Type</label>
          <select
            :class="selectCls"
            :value="config.chartType"
            @change="onTypeChange(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="t in CHART_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
          </select>
        </div>
        <button
          type="button"
          class="rounded-2 border border-outline-gray-2 bg-surface-base p-1.5 text-ink-gray-6 transition-colors hover:bg-surface-gray-2 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!config.dimension || recommending"
          title="Recommend a chart type for this data"
          @click="recommend"
        >
          <Loader2 v-if="recommending" class="h-4 w-4 animate-spin text-primary" />
          <Lightbulb v-else class="h-4 w-4" />
        </button>
        <button
          type="button"
          class="rounded-2 border border-outline-gray-2 bg-surface-base p-1.5 text-ink-gray-6 transition-colors hover:bg-surface-gray-2 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!hasData || explaining"
          title="Explain this chart in plain English"
          @click="explainThisChart"
        >
          <Loader2 v-if="explaining" class="h-4 w-4 animate-spin text-primary" />
          <Sparkles v-else class="h-4 w-4" />
        </button>
        <button
          type="button"
          class="rounded-2 border border-outline-gray-2 bg-surface-base p-1.5 text-ink-gray-6 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-8 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!hasData"
          title="Download chart as PNG"
          @click="exportPng"
        >
          <Download class="h-4 w-4" />
        </button>
        <button
          type="button"
          class="rounded-2 border border-outline-gray-2 bg-surface-base p-1.5 text-ink-gray-4 transition-colors hover:bg-surface-gray-2 hover:text-ink-red"
          title="Remove chart"
          @click="emit('remove')"
        >
          <X class="h-4 w-4" />
        </button>
      </div>
    </div>

    <!-- #18 / #30 AI panels: type recommendation + chart narrative. On-demand and
         dismissible; independent of the plot state below. -->
    <div
      v-if="recommendPanel || recommendError || explainText || explainError"
      class="space-y-2 border-b border-outline-gray-1 bg-primary-1/50 px-4 py-2.5 text-sm"
    >
      <!-- #30 recommendation (already applied to the Type above) + alternatives -->
      <div v-if="recommendPanel" class="flex items-start gap-2">
        <Lightbulb class="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <div class="min-w-0 flex-1">
          <p class="text-ink-gray-8">
            <span class="font-semibold text-primary">{{ typeLabel(recommendPanel.chartType) }}</span>
            — {{ recommendPanel.reasoning }}
          </p>
          <div v-if="recommendPanel.alternatives.length" class="mt-1.5 flex flex-wrap items-center gap-1.5">
            <span class="text-[11px] text-ink-gray-5">Try instead:</span>
            <button
              v-for="alt in recommendPanel.alternatives"
              :key="alt"
              type="button"
              class="rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-0.5 text-[11px] font-medium text-ink-gray-7 transition-colors hover:border-primary-3 hover:text-primary"
              @click="applyType(alt)"
            >
              {{ typeLabel(alt) }}
            </button>
          </div>
        </div>
        <button
          type="button"
          class="rounded-2 p-0.5 text-ink-gray-4 transition-colors hover:bg-surface-base hover:text-ink-gray-7"
          title="Dismiss"
          @click="recommendPanel = null"
        >
          <X class="h-3.5 w-3.5" />
        </button>
      </div>
      <div v-if="recommendError" class="flex items-start gap-2 text-ink-red">
        <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
        <span class="min-w-0 flex-1 break-words">{{ recommendError }}</span>
      </div>

      <!-- #18 narrative of the current series -->
      <div v-if="explainText" class="flex items-start gap-2">
        <Sparkles class="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <p class="min-w-0 flex-1 whitespace-pre-wrap break-words leading-relaxed text-ink-gray-8">
          {{ explainText }}
        </p>
        <button
          type="button"
          class="rounded-2 p-0.5 text-ink-gray-4 transition-colors hover:bg-surface-base hover:text-ink-gray-7"
          title="Dismiss"
          @click="explainText = null"
        >
          <X class="h-3.5 w-3.5" />
        </button>
      </div>
      <div v-if="explainError" class="flex items-start gap-2 text-ink-red">
        <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
        <span class="min-w-0 flex-1 break-words">{{ explainError }}</span>
      </div>
    </div>

    <!-- Plot. The canvas host is always mounted so ECharts has a stable element to
         init into; transient states are overlaid rather than replacing it. -->
    <div class="relative h-[320px] p-2">
      <div ref="chartEl" class="h-full w-full"></div>

      <div
        v-if="loading || error || !hasData || plotHint"
        class="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-surface-base/85 px-6 text-center"
      >
        <Loader2 v-if="loading" class="h-5 w-5 animate-spin text-ink-gray-4" />
        <template v-else-if="error">
          <AlertCircle class="h-5 w-5 text-ink-red" />
          <p class="text-xs text-ink-red">{{ error }}</p>
          <p v-if="missingColumn" class="text-xs text-ink-gray-5">
            A column used by this chart no longer exists — pick another above.
          </p>
        </template>
        <template v-else>
          <BarChart3 class="h-5 w-5 text-ink-gray-3" />
          <p class="text-xs text-ink-gray-5">
            {{
              plotHint
                ? plotHint
                : config.dimension
                  ? 'No rows to chart.'
                  : 'Choose a dimension to group by.'
            }}
          </p>
        </template>
      </div>
    </div>

    <!-- Footer: top-N notice + the compiled SQL, mirroring the transparency of the
         cleaning dialog's dry-run panel. -->
    <div
      v-if="data && hasData"
      class="border-t border-outline-gray-1 px-4 py-2"
    >
      <p v-if="data.truncated" class="mb-1 text-[11px] text-ink-amber">
        Showing the top {{ data.keys.length }} categories only.
      </p>
      <details>
        <summary class="cursor-pointer text-[11px] text-ink-gray-5 hover:text-ink-gray-7">
          Compiled SQL
        </summary>
        <pre class="mt-1 max-h-32 overflow-auto rounded-2 bg-surface-gray-3 p-2 text-[11px] leading-relaxed text-ink-gray-8">{{ data.compiled_sql }}</pre>
      </details>
    </div>
  </div>
</template>
