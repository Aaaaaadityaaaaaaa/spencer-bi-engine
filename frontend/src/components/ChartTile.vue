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
import { computed, nextTick, ref } from 'vue'
import { AlertCircle, BarChart3, Bold, Download, GripVertical, Hash, Lightbulb, Loader2, Palette, Pencil, SlidersHorizontal, Sparkles, X } from '@lucide/vue'
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
  asHexInput,
  CHART_BG_PALETTE,
  CHART_FONT,
  CHART_INK,
  CHART_PALETTE,
  CHART_PRIMARY,
  CHART_SPLIT_LINE,
  normalizeHex,
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

// TASK-038: the field pickers ARE the axis selectors, so label them by where each field
// actually lands on the plot — "what's on X / what's on Y" — instead of BI jargon. The
// mapping is orientation-aware and matches the on-chart axis titles below: a horizontal bar
// swaps the axes (category → Y), and the non-cartesian shapes (pie/treemap/funnel) have no
// axes so they read Category / Value. `series` is only shown when supportsBreakdown().
const axisLabels = computed<{ dim: string; series: string; measure: string }>(() => {
  switch (props.config.chartType) {
    case 'hbar':
      return { dim: 'Y axis', series: 'Breakdown', measure: 'X axis' }
    case 'heatmap':
      return { dim: 'X axis', series: 'Y axis', measure: 'Value (colour)' }
    case 'pie':
    case 'treemap':
    case 'funnel':
      return { dim: 'Category', series: 'Breakdown', measure: 'Value' }
    default: // bar / line / area / stacked → standard vertical cartesian
      return { dim: 'X axis', series: 'Breakdown', measure: 'Y axis' }
  }
})

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

const autoTitle = computed(() => {
  const base = props.config.dimension
    ? `${measureLabel.value} by ${props.config.dimension}`
    : measureLabel.value
  return is2D.value && props.config.series ? `${base}, split by ${props.config.series}` : base
})

// TASK-033: a user-set title overrides the auto one. Every consumer (header, PNG filename,
// #18 explain, #30 recommend) reads `title`, so the override flows everywhere for free.
const title = computed(() => props.config.title?.trim() || autoTitle.value)

// --- TASK-033 presentation controls -----------------------------------------------
// Inline title edit (QueryConsole's savingName idiom: input + enter/esc, confirm on blur).
const editingTitle = ref(false)
const titleDraft = ref('')
const titleInput = ref<HTMLInputElement | null>(null)
function startTitleEdit(): void {
  titleDraft.value = props.config.title ?? ''
  editingTitle.value = true
  void nextTick(() => titleInput.value?.focus())
}
function confirmTitle(): void {
  if (!editingTitle.value) return // guard the blur that fires right after enter/esc
  editingTitle.value = false
  // Keep interior spaces; treat all-whitespace as "no override" (revert to the auto title).
  const raw = titleDraft.value
  const next = raw.trim() === '' ? null : raw
  if (next !== (props.config.title ?? null)) emit('update:config', { ...props.config, title: next })
}
function cancelTitle(): void {
  editingTitle.value = false
}

// Colour swatch popover (ResultsTable's menuOpen + fixed-backdrop idiom, no doc listeners).
const colorOpen = ref(false)
const colorPos = ref<{ x: number; y: number }>({ x: 0, y: 0 })
function toggleColor(e: MouseEvent): void {
  if (colorOpen.value) {
    colorOpen.value = false
    return
  }
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  colorPos.value = { x: r.right, y: r.bottom }
  colorOpen.value = true
}
// The popover carries TWO targets now (series colour + card background) plus custom
// inputs, so picking no longer auto-closes it — the user tweaks both and clicks away
// (the fixed backdrop closes it), matching a Power BI format pane.
function pickColor(c: string | null): void {
  if (c !== (props.config.color ?? null)) emit('update:config', { ...props.config, color: c })
}
function onColorHex(raw: string): void {
  const v = raw.trim()
  if (v === '') return pickColor(null)
  const hex = normalizeHex(v)
  if (hex) pickColor(hex) // ignore an unparseable entry (the field reverts to the shown value)
}
// TASK-036: per-tile card background fill. null ⇒ default surface.
function pickBg(c: string | null): void {
  if (c !== (props.config.bg ?? null)) emit('update:config', { ...props.config, bg: c })
}
function onBgHex(raw: string): void {
  const v = raw.trim()
  if (v === '') return pickBg(null)
  const hex = normalizeHex(v)
  if (hex) pickBg(hex)
}

function toggleValues(): void {
  emit('update:config', { ...props.config, showValues: !props.config.showValues })
}
function toggleClean(): void {
  emit('update:config', { ...props.config, hideControls: !props.config.hideControls })
}
// TASK-036: bold the tile title.
function toggleBold(): void {
  emit('update:config', { ...props.config, bold: !props.config.bold })
}

// TASK-036 #4: per-chart "Top N" categories. `null`/absent ⇒ ChartCanvas's default
// (SERIES_LIMIT = 50). `DEFAULT_TOPN` here is only the number box's placeholder and MUST
// mirror that constant; `TOPN_MAX` is the server's category ceiling, surfaced as "All".
const DEFAULT_TOPN = 50
const TOPN_MAX = 200
const TOPN_PRESETS: { label: string; value: number }[] = [
  { label: '5', value: 5 },
  { label: '10', value: 10 },
  { label: '20', value: 20 },
  { label: 'All', value: TOPN_MAX },
]
function setTopN(v: number): void {
  if (v !== (props.config.topN ?? null)) emit('update:config', { ...props.config, topN: v })
}
function onTopNInput(raw: string): void {
  const trimmed = raw.trim()
  if (trimmed === '') return void emit('update:config', { ...props.config, topN: null })
  const n = Number(trimmed)
  if (!Number.isFinite(n)) return
  const clamped = Math.max(1, Math.min(Math.round(n), TOPN_MAX))
  if (clamped !== (props.config.topN ?? null)) emit('update:config', { ...props.config, topN: clamped })
}

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
// TASK-038: axis-title style — a touch larger + semibold so the "what's on X / what's on Y"
// caption reads distinctly from the tick labels above it.
const axisNameStyle = { color: CHART_INK, fontFamily: CHART_FONT, fontSize: 12, fontWeight: 600 }

// TASK-033 #4: on-graph value labels. `showValues` turns them on across every shape; the
// number formatting matches the KPI cards (localised, <=2 fractional digits). A null/NaN
// datum (an ISO-string metric dropped to null) renders no label rather than "NaN".
const dataLabelStyle = { color: CHART_INK, fontFamily: CHART_FONT, fontSize: 11 }
function fmtLabelValue(v: unknown): string {
  return typeof v === 'number' && Number.isFinite(v)
    ? v.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : ''
}

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
  const showValues = props.config.showValues ?? false

  // Category-axis chrome, shared by every cartesian shape (1-D, 2-D and heatmap).
  // `flat` suppresses the >8-entry label rotation (a horizontal bar reads labels flat).
  // TASK-038: `name` draws the axis title (the field on that axis). `nameGap` is biased
  // large to clear the tick labels — rotated X labels and (flat) Y category labels are
  // taller/wider — because with `grid.outerBoundsContain: 'all'` any excess only reserves
  // gutter, it never clips; too small would let the title overlap the labels.
  const makeCategoryAxis = (labels: string[], flat = false, name?: string | null) => {
    const rotate = !flat && labels.length > 8
    return {
      type: 'category' as const,
      data: labels,
      name: name || undefined,
      nameLocation: 'middle' as const,
      nameGap: flat ? 72 : rotate ? 60 : 30,
      nameTextStyle: axisNameStyle,
      axisLabel: { ...axisLabelStyle, rotate: rotate ? 35 : 0, hideOverlap: true },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: CHART_SPLIT_LINE } },
    }
  }
  // Value axis defaults to a Y-axis gap (vertical, rotated number labels); pass a smaller
  // gap when it sits on X (a horizontal bar's value axis reads flat number labels).
  const makeValueAxis = (name?: string | null, nameGap = 54) => ({
    type: 'value' as const,
    name: name || undefined,
    nameLocation: 'middle' as const,
    nameGap,
    nameTextStyle: axisNameStyle,
    axisLabel: axisLabelStyle,
    axisLine: { show: false },
    splitLine: { lineStyle: { color: CHART_SPLIT_LINE } },
  })

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
          outerBoundsContain: 'all',
        },
        xAxis: { ...makeCategoryAxis(xlabels, false, props.config.dimension), splitArea: { show: true } },
        yAxis: {
          type: 'category' as const,
          data: slabels,
          name: props.config.series || undefined,
          nameLocation: 'middle' as const,
          nameGap: 72,
          nameTextStyle: axisNameStyle,
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
            label: {
              show: showValues,
              color: CHART_INK,
              fontFamily: CHART_FONT,
              fontSize: 10,
              formatter: (p: { value: [number, number, number] }) => fmtLabelValue(p.value[2]),
            },
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
      label: {
        show: showValues,
        position: isBar && stack ? 'inside' : 'top',
        ...dataLabelStyle,
        formatter: (p: { value: number | null }) => fmtLabelValue(p.value),
      },
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
        outerBoundsContain: 'all',
      },
      tooltip: { trigger: 'axis', axisPointer: { type: isBar ? 'shadow' : 'line' } },
      legend: { type: 'scroll', top: 4, textStyle: axisLabelStyle },
      xAxis: makeCategoryAxis(xlabels, false, props.config.dimension),
      yAxis: makeValueAxis(measureLabel.value),
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
          label: {
            show: showValues,
            formatter: '{b}: {c}',
            color: CHART_INK,
            fontFamily: CHART_FONT,
            fontSize: 11,
          },
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
          label: { show: true, formatter: showValues ? '{b}\n{c}' : '{b}', color: 'oklch(1 0 0)', fontFamily: CHART_FONT },
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
            formatter: showValues ? '{b} {c}' : '{b}',
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
  // TASK-033 #3: a per-tile colour overrides the brand primary for this single-series shape.
  // (A breakdown draws the categorical palette instead — handled in the 2-D block above.)
  const accent = props.config.color || CHART_PRIMARY

  const categoryAxis = makeCategoryAxis(labels, isHorizontal, props.config.dimension)

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
      outerBoundsContain: 'all',
    },
    tooltip: { trigger: 'axis', axisPointer: { type: isBarSeries ? 'shadow' : 'line' } },
    // hbar swaps the axes: value on X (bottom, flat number labels → small gap), category on
    // Y. Every other cartesian shape keeps category on X, value on Y.
    xAxis: isHorizontal ? makeValueAxis(measureLabel.value, 30) : categoryAxis,
    yAxis: isHorizontal ? categoryAxis : makeValueAxis(measureLabel.value),
    series: [
      {
        type: isBarSeries ? 'bar' : 'line',
        name: measureLabel.value,
        data: seriesData,
        barMaxWidth: 48,
        label: {
          show: showValues,
          position: isHorizontal ? 'right' : 'top',
          ...dataLabelStyle,
          formatter: (p: { value: number | null }) => fmtLabelValue(p.value),
        },
        itemStyle: {
          color: accent,
          borderRadius: isBarSeries ? (isHorizontal ? [0, 3, 3, 0] : [3, 3, 0, 0]) : 0,
        },
        lineStyle: isBarSeries ? undefined : { width: 2, color: accent },
        areaStyle: isArea ? { opacity: 0.15, color: accent } : undefined,
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
  <div
    class="tile-drag-handle group flex h-full flex-col overflow-hidden rounded-5 border border-outline-gray-1 bg-surface-base shadow-sm"
    :style="config.bg ? { backgroundColor: config.bg } : undefined"
  >
    <!-- Header. TASK-036: when a custom card fill is set the header goes transparent so the
         fill reads as one uniform card (Power BI); otherwise it keeps the subtle grey band. -->
    <div
      class="flex flex-wrap items-end justify-between gap-3 border-b border-outline-gray-1 px-4 py-3"
      :class="config.bg ? 'bg-transparent' : 'bg-surface-gray-1'"
    >
      <h3 class="flex min-w-0 flex-1 items-center gap-1.5 text-sm font-semibold text-ink-gray-8">
        <!-- Drag grip: a visible "you can move this" affordance. TASK-036 made the whole
             card root the `.tile-drag-handle`, so a drag can start anywhere on the tile that
             isn't an interactive control / the plot canvas — the grip just advertises it.
             Hidden in present/export via js-export-exclude. -->
        <span
          class="tile-drag-handle js-export-exclude -ml-1 flex shrink-0 cursor-grab items-center text-ink-gray-3 opacity-0 transition-opacity hover:text-ink-gray-6 group-hover:opacity-100 active:cursor-grabbing"
          title="Drag to move"
        >
          <GripVertical class="h-4 w-4" />
        </span>
        <BarChart3 class="h-4 w-4 shrink-0 text-primary" />
        <!-- TASK-033: inline-editable title (QueryConsole savingName idiom). The title text
             itself is NOT js-export-exclude, so it stays in the exported/presented board. -->
        <input
          v-if="editingTitle"
          ref="titleInput"
          v-model="titleDraft"
          type="text"
          class="min-w-0 flex-1 rounded-2 border border-outline-gray-2 bg-surface-base px-1.5 py-0.5 text-sm text-ink-gray-8 focus:border-primary-5 focus:outline-none"
          :placeholder="autoTitle"
          @keydown.enter="confirmTitle"
          @keydown.esc="cancelTitle"
          @blur="confirmTitle"
        />
        <template v-else>
          <span class="cursor-move truncate" :class="config.bold ? 'font-bold' : ''" :title="title">{{ title }}</span>
          <button
            type="button"
            class="js-export-exclude shrink-0 rounded-2 p-0.5 text-ink-gray-4 opacity-0 transition-opacity hover:bg-surface-gray-2 hover:text-ink-gray-7 group-hover:opacity-100 focus:opacity-100"
            title="Rename tile"
            @click="startTitleEdit"
          >
            <Pencil class="h-3 w-3" />
          </button>
        </template>
      </h3>

      <div class="js-export-exclude flex flex-wrap items-end justify-end gap-2">
        <!-- Full picker strip — collapsed by the clean toggle (#5), always hidden in
             present/export (this whole group is js-export-exclude). -->
        <template v-if="!config.hideControls">
          <div>
            <label :class="labelCls">{{ axisLabels.dim }}</label>
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
            <label :class="labelCls">{{ axisLabels.series }}</label>
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
            <label :class="labelCls">{{ axisLabels.measure }}</label>
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
          <!-- TASK-036 #4: per-chart Top-N. Number box + quick presets; the server sorts a
               categorical series by measure DESC, so this is the TRUE top-N by value. Only
               meaningful once a dimension (group-by) is chosen. -->
          <div v-if="config.dimension">
            <label :class="labelCls">Show top</label>
            <div class="flex items-center gap-1">
              <input
                type="number"
                min="1"
                :max="TOPN_MAX"
                inputmode="numeric"
                :class="[selectCls, 'w-16']"
                :value="config.topN ?? ''"
                :placeholder="String(DEFAULT_TOPN)"
                :title="`Top categories to show (max ${TOPN_MAX})`"
                @change="onTopNInput(($event.target as HTMLInputElement).value)"
              />
              <button
                v-for="p in TOPN_PRESETS"
                :key="p.label"
                type="button"
                class="rounded-2 border px-1.5 py-1 text-[11px] transition-colors"
                :class="config.topN === p.value
                  ? 'border-primary-3 bg-primary-1 text-primary'
                  : 'border-outline-gray-2 bg-surface-base text-ink-gray-6 hover:bg-surface-gray-2 hover:text-primary'"
                :title="p.label === 'All' ? `Show up to ${TOPN_MAX}` : `Show top ${p.value}`"
                @click="setTopN(p.value)"
              >
                {{ p.label }}
              </button>
            </div>
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
        </template>

        <!-- Presentation toolbar (#3/#4/#5 + remove). Always available so a cleaned tile can
             be recoloured / restored; itself js-export-exclude, so present/export hide it. -->
        <div class="flex items-center gap-0.5 self-end">
          <button
            type="button"
            class="rounded-2 border border-outline-gray-2 bg-surface-base p-1.5 transition-colors hover:bg-surface-gray-2"
            :class="config.color || config.bg ? 'text-primary' : 'text-ink-gray-6 hover:text-primary'"
            title="Colour &amp; card background"
            @click="toggleColor"
          >
            <Palette class="h-4 w-4" />
          </button>
          <button
            type="button"
            class="rounded-2 border border-outline-gray-2 bg-surface-base p-1.5 transition-colors hover:bg-surface-gray-2"
            :class="config.bold ? 'text-primary' : 'text-ink-gray-6 hover:text-primary'"
            :title="config.bold ? 'Unbold title' : 'Bold title'"
            @click="toggleBold"
          >
            <Bold class="h-4 w-4" />
          </button>
          <button
            type="button"
            class="rounded-2 border border-outline-gray-2 bg-surface-base p-1.5 transition-colors hover:bg-surface-gray-2"
            :class="config.showValues ? 'text-primary' : 'text-ink-gray-6 hover:text-primary'"
            :title="config.showValues ? 'Hide values on chart' : 'Show values on chart'"
            @click="toggleValues"
          >
            <Hash class="h-4 w-4" />
          </button>
          <button
            type="button"
            class="rounded-2 border border-outline-gray-2 bg-surface-base p-1.5 transition-colors hover:bg-surface-gray-2"
            :class="config.hideControls ? 'text-primary' : 'text-ink-gray-6 hover:text-primary'"
            :title="config.hideControls ? 'Show controls' : 'Hide controls (keep title + chart)'"
            @click="toggleClean"
          >
            <SlidersHorizontal class="h-4 w-4" />
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
    </div>

    <!-- TASK-033/036 colour popover (ResultsTable menuOpen + fixed-backdrop idiom). Two
         targets — series colour + card background — each with presets, a native any-colour
         picker, a hex field, and a reset. `.no-drag` keeps the floating panel from starting a
         tile drag. Picking does NOT close the panel, so both sections stay usable. -->
    <template v-if="colorOpen">
      <div class="js-export-exclude no-drag fixed inset-0 z-40" @click="colorOpen = false"></div>
      <div
        class="js-export-exclude no-drag fixed z-50 max-h-[70vh] w-56 overflow-auto rounded-3 border border-outline-gray-2 bg-surface-base p-2.5 shadow-lg"
        :style="{ top: `${colorPos.y + 4}px`, left: `${colorPos.x}px`, transform: 'translateX(-100%)' }"
      >
        <!-- Series colour -->
        <p class="mb-1.5 px-0.5 text-[11px] font-medium text-ink-gray-6">
          Series colour
          <span v-if="is2D" class="block text-[10px] font-normal text-ink-gray-4">
            (a breakdown uses the category palette)
          </span>
        </p>
        <div class="grid grid-cols-4 gap-1.5">
          <button
            v-for="c in CHART_PALETTE"
            :key="c"
            type="button"
            class="h-7 w-7 rounded-2 border transition-transform hover:scale-110"
            :class="config.color === c ? 'border-ink-gray-8 ring-1 ring-ink-gray-8' : 'border-outline-gray-2'"
            :style="{ backgroundColor: c }"
            :title="c"
            @click="pickColor(c)"
          ></button>
        </div>
        <div class="mt-2 flex items-center gap-1.5">
          <input
            type="color"
            class="h-7 w-8 shrink-0 cursor-pointer rounded-2 border border-outline-gray-2 bg-surface-base p-0.5"
            :value="asHexInput(config.color)"
            title="Custom colour"
            @change="pickColor(($event.target as HTMLInputElement).value)"
          />
          <input
            type="text"
            class="w-full min-w-0 rounded-2 border border-outline-gray-2 bg-surface-base px-1.5 py-1 text-[11px] text-ink-gray-8 focus:border-primary-5 focus:outline-none"
            :value="config.color ?? ''"
            placeholder="#hex / preset"
            @change="onColorHex(($event.target as HTMLInputElement).value)"
            @keydown.enter="onColorHex(($event.target as HTMLInputElement).value)"
          />
          <button
            type="button"
            class="shrink-0 rounded-2 border border-outline-gray-2 px-2 py-1 text-[11px] transition-colors hover:bg-surface-gray-2"
            :class="config.color ? 'text-ink-gray-7' : 'text-primary'"
            title="Default (brand) colour"
            @click="pickColor(null)"
          >
            Auto
          </button>
        </div>

        <!-- Card background -->
        <div class="mt-3 border-t border-outline-gray-1 pt-2">
          <p class="mb-1.5 px-0.5 text-[11px] font-medium text-ink-gray-6">Card background</p>
          <div class="grid grid-cols-4 gap-1.5">
            <button
              v-for="c in CHART_BG_PALETTE"
              :key="c"
              type="button"
              class="h-7 w-7 rounded-2 border transition-transform hover:scale-110"
              :class="config.bg === c ? 'border-ink-gray-8 ring-1 ring-ink-gray-8' : 'border-outline-gray-2'"
              :style="{ backgroundColor: c }"
              :title="c"
              @click="pickBg(c)"
            ></button>
          </div>
          <div class="mt-2 flex items-center gap-1.5">
            <input
              type="color"
              class="h-7 w-8 shrink-0 cursor-pointer rounded-2 border border-outline-gray-2 bg-surface-base p-0.5"
              :value="asHexInput(config.bg, '#ffffff')"
              title="Custom background"
              @change="pickBg(($event.target as HTMLInputElement).value)"
            />
            <input
              type="text"
              class="w-full min-w-0 rounded-2 border border-outline-gray-2 bg-surface-base px-1.5 py-1 text-[11px] text-ink-gray-8 focus:border-primary-5 focus:outline-none"
              :value="config.bg ?? ''"
              placeholder="#hex"
              @change="onBgHex(($event.target as HTMLInputElement).value)"
              @keydown.enter="onBgHex(($event.target as HTMLInputElement).value)"
            />
            <button
              type="button"
              class="shrink-0 rounded-2 border border-outline-gray-2 px-2 py-1 text-[11px] transition-colors hover:bg-surface-gray-2"
              :class="config.bg ? 'text-ink-gray-7' : 'text-primary'"
              title="No fill (default surface)"
              @click="pickBg(null)"
            >
              None
            </button>
          </div>
        </div>
      </div>
    </template>

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
         init into; transient states are overlaid rather than replacing it. `flex-1 min-h-0`
         lets the plot fill the tile's remaining height (TASK-034 resizable tiles) — the
         useEchart ResizeObserver re-renders ECharts when this box changes. -->
    <div class="relative min-h-0 flex-1 p-2">
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
                  : `Choose a field for the ${axisLabels.dim}.`
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
