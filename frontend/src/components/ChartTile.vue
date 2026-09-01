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
import { computed, nextTick, ref, watch } from 'vue'
import { AlertCircle, BarChart3, Bold, Copy, GripVertical, Lightbulb, ListOrdered, Loader2, Palette, Pencil, SlidersHorizontal, Sparkles, X } from '@lucide/vue'
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
import { supportsBreakdown, supportsMeasureY } from '../types'
import { useSession } from '../composables/useSession'
import { formatNumber, resolvedColor } from '../composables/useDashboardSettings'
import { apiErrorMessage, explainChart, recommendChart } from '../services/api'
import { useEchart } from '../composables/useEchart'
import { AGG_LABEL, allowedAggregations, coerceAggregation } from '../utils/aggregations'
import { dimensionColumns, numericColumns } from '../utils/columnKind'
import {
  asHexInput,
  CHART_BG_PALETTE,
  CHART_FONT,
  CHART_INK,
  CHART_INK_FAINT,
  CHART_PALETTE,
  CHART_PALETTES,
  CHART_PRIMARY,
  CHART_SPLIT_LINE,
  CHART_WHITE,
  normalizeHex,
  paletteColorFor,
  paletteById,
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
  // True while this tile's editor is shown in the side drawer (Power BI–style). When false
  // the inline controls are hidden so the visual stays clean; when true they teleport to the drawer.
  selected?: boolean
}>()

const emit = defineEmits<{
  'update:config': [config: ChartConfig]
  remove: []
  duplicate: []
  // A bar/slice was clicked: the raw dimension key, for ChartCanvas to cross-filter on.
  select: [key: AggregateKey]
  // The tile body was clicked — ChartCanvas opens this tile's settings in the side drawer.
  'open-settings': []
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
  { value: 'scatter', label: 'Scatter' },
  { value: 'box', label: 'Box plot' },
  { value: 'gauge', label: 'Gauge' },
  { value: 'slicer', label: 'Slicer (Dropdown)' },
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

// Wave 5 scatter: a Y-measure picker, shown only for the scatter type. The measure
// select already holds the X axis; this holds the Y axis. Only numeric columns qualify.
const showYMeasure = computed(() => supportsMeasureY(props.config.chartType))
const yMeasureOptions = computed(() => numericColumns(props.columns))

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
const axisLabels = computed<{ dim: string; series: string; measure: string; measureY?: string }>(() => {
  switch (props.config.chartType) {
    case 'hbar':
      return { dim: 'Y axis', series: 'Breakdown', measure: 'X axis' }
    case 'heatmap':
      return { dim: 'X axis', series: 'Y axis', measure: 'Value (colour)' }
    case 'pie':
    case 'treemap':
    case 'funnel':
      return { dim: 'Category', series: 'Breakdown', measure: 'Value' }
    case 'slicer':
      return { dim: 'Filter column', series: 'Breakdown', measure: 'Value (ignored)' }
    case 'scatter':
      return { dim: 'Colour / group', series: 'Breakdown', measure: 'X axis', measureY: 'Y axis' }
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

const isCartesian = computed(() => ['bar', 'line', 'area', 'hbar', 'stacked', 'scatter', 'box'].includes(props.config.chartType))
const isLine = computed(() => ['line', 'area'].includes(props.config.chartType))
const isArea = computed(() => props.config.chartType === 'area')
const canStack = computed(() => ['stacked', 'area', 'bar'].includes(props.config.chartType))
const canLegend = computed(() => is2D.value || ['pie', 'funnel', 'scatter'].includes(props.config.chartType))

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
const colorMaxH = ref(360)
function toggleColor(e: MouseEvent): void {
  if (colorOpen.value) {
    colorOpen.value = false
    return
  }
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  const margin = 8
  const estH = 380
  const vh = window.innerHeight
  // Anchor below the button, but flip above it when there isn't room — keeps the whole
  // menu on-screen so the lower swatches/inputs stay reachable (and scrollable).
  let top = r.bottom + 4
  if (top + estH > vh - margin) top = Math.max(margin, r.top - estH - 4)
  colorPos.value = { x: r.right, y: top }
  colorMaxH.value = Math.max(160, Math.min(estH, vh - top - margin))
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

// The "is there anything to draw" test is type-dependent: scatter reports `points`,
// box reports `boxes`, gauge reads the single KPI `values`, everything else reports `keys`.
const hasData = computed(() => {
  const d = props.data
  if (!d) return false
  switch (props.config.chartType) {
    case 'scatter':
      return (d.points?.length ?? 0) > 0
    case 'box':
      return (d.boxes?.length ?? 0) > 0
    case 'gauge':
      return (d.values?.length ?? 0) > 0
    default:
      return (d.keys?.length ?? 0) > 0
  }
})

// When the tile has data in hand but the chosen type can't draw it yet (a heatmap with
// no breakdown selected), guide the user instead of leaving a blank canvas.
const plotHint = computed<string | null>(() => {
  // Wave 5 scatter: prompt for the two measures up front, independent of data arrival.
  if (props.config.chartType === 'scatter') {
    if (!props.config.measure || !props.config.measureY) return 'Pick an X measure and a Y measure.'
    return null
  }
  // Wave 5 box plot: needs a category (x) and a numeric measure (y).
  if (props.config.chartType === 'box') {
    if (!props.config.dimension) return 'Pick a category field (x) and a measure (y).'
    return null
  }
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

function fmtLabelValue(v: unknown): string {
  return typeof v === 'number' && Number.isFinite(v) ? formatNumber(v) : ''
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
    const axisLabelStyle = { color: CHART_INK, fontFamily: props.config.fontFamily || CHART_FONT, fontSize: props.config.valueFontSize || 11 }
    const axisNameStyle = { color: CHART_INK, fontFamily: props.config.fontFamily || CHART_FONT, fontSize: (props.config.valueFontSize || 11) + 1, fontWeight: 600 }
    const dataLabelStyle = { color: CHART_INK, fontFamily: props.config.fontFamily || CHART_FONT, fontSize: props.config.valueFontSize || 11 }
    const t = props.config.chartType
    const showValues = props.config.showValues ?? false
    if (t === 'slicer') return null
    // TASK-044: drawer-driven presentation toggles (all default-on for back-compat).
    const showLegend = props.config.showLegend !== false
    const showGrid = props.config.showGrid !== false
    const yScaleType = props.config.yScale === 'log' ? 'log' : 'value'
    const smoothLines = props.config.smooth !== false
    const showMarkers = props.config.showMarkers !== false
    const areaOpacity = props.config.areaOpacity ?? 0.2
    const pc = (j: number) => paletteColorFor(props.config.palette, j)
    const refVal = props.config.referenceValue ?? null
    const legendOf = (extra: Record<string, unknown>) => (showLegend ? extra : { show: false })
    const markLineOf = () =>
      refVal === null
        ? undefined
        : {
            silent: true,
            symbol: 'none' as const,
            lineStyle: { color: CHART_INK_FAINT, type: 'dashed' as const, width: 1 },
            label: { show: true, position: 'end' as const, color: CHART_INK, fontSize: 10, formatter: 'ref' },
            data: [{ yAxis: refVal }],
          }
    // Category sort permutation. 'auto' mirrors Top-N (value DESC); 'alpha' sorts labels.
    const sortPerm = <T>(keys: T[], vals: Array<number | null>): number[] => {
      const dir = props.config.sortDir ?? 'auto'
      const idx = keys.map((_, i) => i)
      if (dir === 'asc') return idx.sort((a, b) => (vals[a] ?? Infinity) - (vals[b] ?? Infinity))
      if (dir === 'alpha') return idx.sort((a, b) => String(keys[a]).localeCompare(String(keys[b])))
      return idx.sort((a, b) => (vals[b] ?? -Infinity) - (vals[a] ?? -Infinity))
    }

  // Category-axis chrome, shared by every cartesian shape (1-D, 2-D and heatmap).
  // `flat` suppresses the >8-entry label rotation (a horizontal bar reads labels flat).
  // TASK-038: `name` draws the axis title (the field on that axis). `nameGap` clears the tick
  // labels so the title never overlaps them; kept modest so that under the cartesian grids'
  // `outerBoundsContain: 'axisLabel'` (TASK-041 #1) the title still lands inside the small
  // outer margin. On very dense (rotated) or flat category axes the title may sit tight.
  const makeCategoryAxis = (labels: string[], flat = false, name?: string | null) => {
    const rotate = !flat && labels.length > 8
    return {
      type: 'category' as const,
      data: labels,
      name: name || undefined,
      nameLocation: 'middle' as const,
      nameGap: flat ? 44 : rotate ? 38 : 22,
      nameTextStyle: axisNameStyle,
      axisLabel: { ...axisLabelStyle, rotate: rotate ? 35 : 0, hideOverlap: true },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: CHART_SPLIT_LINE } },
    }
  }
  // Value axis. TASK-041 #1: the tick NUMBERS must be visible at any tile size. The grids
  // below use `outerBoundsContain: 'axisLabel'` (the classic containLabel behaviour) so the
  // number gutter is always reserved; and we keep the axis NAME slim by drawing it vertical
  // on Y (nameRotate 90) — a wide *horizontal* Y-title (the TASK-038 default) is what had been
  // squeezing the numbers off small tiles under the old 'all' containment. hbar's value axis
  // sits on X, so it passes nameRotate 0 to keep that title horizontal below the axis.
  const makeValueAxis = (name?: string | null, nameGap = 46, nameRotate = 90) => ({
    type: yScaleType,
    name: name || undefined,
    nameLocation: 'middle' as const,
    nameGap,
    nameRotate,
    nameTextStyle: axisNameStyle,
    axisLabel: axisLabelStyle,
    axisLine: { show: false },
    splitLine: { show: showGrid, lineStyle: { color: CHART_SPLIT_LINE } },
  })

  // ---- Scatter (Wave 5) -----------------------------------------------------------
  // Raw (x, y) points from the backend. Optional `dimension` becomes a colour group;
  // each group is its own series so the legend splits them. Null x/y points are skipped.
  if (t === 'scatter') {
    const pts = (d.points ?? []).filter(
      (p) => toNumber(p.x) !== null && toNumber(p.y) !== null,
    )
    if (pts.length === 0) return null
    const groups = new Map<string, Array<[number, number]>>()
    for (const p of pts) {
      const x = toNumber(p.x)!
      const y = toNumber(p.y)!
      const gkey = p.group === undefined ? '' : String(p.group)
      if (!groups.has(gkey)) groups.set(gkey, [])
      groups.get(gkey)!.push([x, y])
    }
    const entries = [...groups.entries()]
    const series = entries.map(([gkey, data], j) => ({
      type: 'scatter' as const,
      name: gkey === '' ? '(all)' : gkey,
      data,
      symbolSize: 7,
      itemStyle: { color: pc(j) },
      markLine: markLineOf(),
    }))
    return {
      grid: {
        left: 24,
        right: 16,
        top: entries.length > 1 ? 34 : 18,
        bottom: 22,
        outerBoundsMode: 'same',
        outerBoundsContain: 'axisLabel',
      },
      tooltip: {
        trigger: 'item',
        formatter: (p: { seriesName: string; value: [number, number] }) =>
          `${p.seriesName}: (${p.value[0]}, ${p.value[1]})`,
      },
      legend: entries.length > 1 ? legendOf({ type: 'scroll', top: 4, textStyle: axisLabelStyle }) : { show: false },
      xAxis: makeValueAxis(props.config.xTitle ?? props.config.measure ?? 'x', 40, 0),
      yAxis: makeValueAxis(props.config.yTitle ?? axisLabels.value.measureY ?? 'Y axis'),
      series,
    }
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
            itemStyle: { borderColor: CHART_WHITE, borderWidth: 1 },
          },
        ],
      }
    }

    // Multi-series cartesian: grouped bar / stacked bar / multi-line / stacked area.
    // One series per breakdown value, each a column of the matrix. `area` and `stacked`
    // stack onto one total; `bar` groups side-by-side; `line` overlays.
    const isBar = t === 'bar' || t === 'stacked'
    const stack = t === 'stacked' || t === 'area' ? 'total' : undefined
    // TASK-044: optional 100% stacked — each row's cells become % of that row's total.
    const pct = props.config.stacked100 === true && !!stack
    const rowTotals = matrix.map((row) => row.reduce((s: number, raw) => s + (toNumber(raw) ?? 0), 0))
    const rowOrder = sortPerm(xlabels, rowTotals)
    displayOrder = rowOrder
    const xlabelsS = rowOrder.map((i) => xlabels[i])
    const matrixS = rowOrder.map((i) => matrix[i])
    const cellVal = (raw: AggregateValue, ri: number): number =>
      pct && rowTotals[ri] ? ((toNumber(raw) ?? 0) / rowTotals[ri]) * 100 : (toNumber(raw) ?? 0)
    const series = slabels.map((name, j) => ({
      type: (isBar ? 'bar' : 'line') as 'bar' | 'line',
      name,
      stack,
      data: matrixS.map((row, ri) => cellVal(row[j], ri)),
      barMaxWidth: 48,
      itemStyle: { color: pc(j) },
      lineStyle: isBar ? undefined : { width: 2, color: pc(j) },
      areaStyle: t === 'area' ? { opacity: areaOpacity, color: pc(j) } : undefined,
      label: {
        show: showValues,
        position: isBar && stack ? 'inside' : 'top',
        ...dataLabelStyle,
        formatter: (p: { value: number | null }) => fmtLabelValue(p.value),
      },
      smooth: smoothLines && !isBar,
      symbol: showMarkers ? 'circle' : 'none',
      symbolSize: 6,
      markLine: markLineOf(),
    }))
    return {
      grid: {
        left: 24,
        right: 16,
        top: 34,
        bottom: 22,
        outerBoundsMode: 'same',
        outerBoundsContain: 'axisLabel',
      },
      tooltip: { trigger: 'axis', axisPointer: { type: isBar ? 'shadow' : 'line' } },
      legend: legendOf({ type: 'scroll', top: 4, textStyle: axisLabelStyle }),
      xAxis: makeCategoryAxis(xlabelsS, false, props.config.xTitle ?? props.config.dimension),
      yAxis: makeValueAxis(
        props.config.yTitle ?? (pct ? `${measureLabel.value} (%)` : measureLabel.value),
      ),
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
      legend: legendOf({
        type: 'scroll',
        orient: 'vertical',
        right: 8,
        top: 'middle',
        textStyle: axisLabelStyle,
      }),
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
          itemStyle: { borderColor: CHART_WHITE, borderWidth: 2 },
          data: labels.map((name, i) => ({
            name,
            value: values[i] ?? 0,
            itemStyle: { color: pc(i), opacity: itemOpacity(d.keys[i]) },
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
          label: { show: true, formatter: showValues ? '{b}\n{c}' : '{b}', color: CHART_WHITE, fontFamily: CHART_FONT },
          itemStyle: { borderColor: CHART_WHITE, borderWidth: 2, gapWidth: 2 },
          data: labels.map((name, i) => ({
            name,
            value: values[i] ?? 0,
            itemStyle: { color: pc(i), opacity: itemOpacity(d.keys[i]) },
          })),
        },
      ],
    }
  }

  if (t === 'funnel') {
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c}' },
      legend: legendOf({ type: 'scroll', bottom: 0, textStyle: axisLabelStyle }),
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
            color: CHART_WHITE,
            fontFamily: CHART_FONT,
            fontSize: 11,
          },
          labelLine: { show: false },
          itemStyle: { borderColor: CHART_WHITE, borderWidth: 1 },
          data: labels.map((name, i) => ({
            name,
            value: values[i] ?? 0,
            itemStyle: { color: pc(i), opacity: itemOpacity(d.keys[i]) },
          })),
        },
      ],
    }
  }

  // ---- Wave 5 box plot ----------------------------------------------------------
  if (t === 'box') {
    const bx = (d.boxes ?? []).filter((b) => b.min !== null && b.max !== null)
    if (bx.length === 0) return null
    const cats = bx.map((b) => (b.key === null ? '(null)' : String(b.key)))
    const data = bx.map((b) => [
      toNumber(b.min),
      toNumber(b.q1),
      toNumber(b.median),
      toNumber(b.q3),
      toNumber(b.max),
    ])
    return {
      grid: { left: 24, right: 16, top: 16, bottom: 22, outerBoundsMode: 'same', outerBoundsContain: 'axisLabel' },
      tooltip: {
        trigger: 'item',
        formatter: (p: { dataIndex: number }) => {
          const b = bx[p.dataIndex]
          return `${cats[p.dataIndex]}<br/>min ${fmtLabelValue(b.min)}<br/>Q1 ${fmtLabelValue(b.q1)}<br/>median ${fmtLabelValue(b.median)}<br/>Q3 ${fmtLabelValue(b.q3)}<br/>max ${fmtLabelValue(b.max)}`
        },
      },
      xAxis: makeCategoryAxis(cats, false, props.config.dimension),
      yAxis: makeValueAxis(measureLabel.value),
      series: [
        {
          type: 'boxplot',
          data,
          itemStyle: { color: CHART_PRIMARY, borderColor: CHART_INK, borderWidth: 1 },
        },
      ],
    }
  }

  // ---- Wave 5 gauge (single KPI dial) -------------------------------------------
  if (t === 'gauge') {
    const v = toNumber(d.values?.[0] ?? null)
    if (v === null) return null
    const gmax = v <= 0 ? 1 : Math.ceil(v * 1.2)
    return {
      tooltip: { formatter: () => fmtLabelValue(v) },
      series: [
        {
          type: 'gauge',
          min: 0,
          max: gmax,
          startAngle: 210,
          endAngle: -30,
          progress: { show: true, width: 12 },
          axisLine: { lineStyle: { width: 12, color: [[1, CHART_SPLIT_LINE]] } },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          pointer: { show: true, length: '60%', width: 4, itemStyle: { color: CHART_PRIMARY } },
          detail: {
            valueAnimation: true,
            fontSize: 22,
            fontFamily: CHART_FONT,
            color: CHART_INK,
            offsetCenter: [0, '40%'],
            formatter: (val: number) => fmtLabelValue(val),
          },
          data: [{ value: v }],
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
  // (A breakdown draws the categorical palette instead)
  const accent = props.config.color ? resolvedColor(props.config.color) : paletteById(props.config.palette)[0]

  // TASK-044: optional category re-sort (display only; clicks map back via `displayOrder`).
  const order1 = sortPerm(labels, values)
  displayOrder = order1
  const labelsS = order1.map((i) => labels[i])
  const valuesS = order1.map((i) => values[i])

  const categoryAxis = makeCategoryAxis(labelsS, isHorizontal, props.config.xTitle ?? props.config.dimension)

  // Per-bar opacity only when this tile owns the cross-filter (and only for bar/hbar —
  // a line/area with a single bright point would read as broken). Otherwise the series
  // takes the plain number array, keeping the unfiltered path allocation-free.
  const seriesData =
    props.activeKey !== undefined && isBarSeries
      ? valuesS.map((v, i) => ({ value: v, itemStyle: { opacity: itemOpacity(d.keys[order1[i]]) } }))
      : valuesS

  return {
    // ECharts 6 deprecated `grid.containLabel`; `outerBoundsMode: 'same'` +
    // `outerBoundsContain: 'axisLabel'` is its documented equivalent — it reserves the
    // tick-label gutter so the value NUMBERS always show at any tile size (TASK-041 #1).
    // left/bottom carry a little extra margin so the axis TITLES (which 'axisLabel' does
    // not itself reserve room for) still have somewhere to land.
    grid: {
      left: 24,
      right: 16,
      top: 16,
      bottom: 22,
      outerBoundsMode: 'same',
      outerBoundsContain: 'axisLabel',
    },
    tooltip: { trigger: 'axis', axisPointer: { type: isBarSeries ? 'shadow' : 'line' } },
    // hbar swaps the axes: value on X (bottom, flat number labels → small gap, title stays
    // horizontal below → nameRotate 0), category on Y. Every other cartesian shape keeps
    // category on X, value on Y (with a slim vertical Y title, nameRotate 90 by default).
    xAxis: isHorizontal ? makeValueAxis(props.config.yTitle ?? measureLabel.value, 30, 0) : categoryAxis,
    yAxis: isHorizontal ? categoryAxis : makeValueAxis(props.config.yTitle ?? measureLabel.value),
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
        areaStyle: isArea ? { opacity: areaOpacity, color: accent } : undefined,
        symbol: showMarkers ? 'circle' : 'none',
        symbolSize: 6,
        smooth: smoothLines && !isBarSeries,
        markLine: markLineOf(),
      },
    ],
  }
})

// TASK-044: when the category order is re-sorted for display, ECharts' dataIndex no longer
// lines up with `d.keys`. `displayOrder` holds the permutation (display index → original
// index) so a click still maps back to the correct raw key for cross-filtering.
let displayOrder: number[] = []

// Map an ECharts click (reported by data index) back to the raw dimension key and bubble
// it up; ChartCanvas turns it into a cross-filter. Only the types whose dataIndex indexes
// the primary keys[] participate (a heatmap cell / treemap tile / funnel stage does not).
function onSliceClick(dataIndex: number): void {
  if (!CROSS_FILTER_TYPES.has(props.config.chartType)) return
  const d = props.data
  if (!d || dataIndex < 0 || dataIndex >= d.keys.length) return
  const orig = displayOrder.length ? displayOrder[dataIndex] ?? dataIndex : dataIndex
  if (orig < 0 || orig >= d.keys.length) return
  emit('select', d.keys[orig])
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

function onMeasureYChange(raw: string): void {
  emit('update:config', { ...props.config, measureY: raw === '' ? null : raw })
}

function onAggChange(raw: string): void {
  emit('update:config', { ...props.config, aggregation: raw as Aggregation })
}

function onTypeChange(raw: string): void {
  const chartType = raw as ChartType
  // Switching away from scatter drops the Y measure so a stale value is never sent.
  emit('update:config', {
    ...props.config,
    chartType,
    measureY: chartType === 'scatter' ? props.config.measureY ?? null : null,
  })
}

// TASK-044: generic config patch used by the style drawer controls.
function patch(p: Partial<ChartConfig>): void {
  emit('update:config', { ...props.config, ...p })
}

// TASK-044: per-tile card chrome (border / corner radius / drop shadow) driven by config.
const cardClass = computed(() => {
  const r = props.config.radius ?? 'md'
  const radius = r === 'sm' ? 'rounded-3' : r === 'lg' ? 'rounded-6' : 'rounded-5'
  const border = props.config.border === false ? 'border-0' : 'border border-outline-gray-1 shadow-sm'
  const shadow = props.config.shadow === false ? '' : 'hover:shadow-md hover:-translate-y-0.5 transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]'
  return `group tile-drag-handle flex h-full flex-col overflow-hidden bg-surface-base ${radius} ${border} ${shadow}`
})

function clampPct(raw: string): number | null {
  const n = Number(raw)
  return Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : null
}
function numOrNull(raw: string): number | null {
  const s = raw.trim()
  if (s === '') return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}
// TASK-044: Reset wipes every style override so the tile falls back to the defaults.
const STYLE_DEFAULTS: Partial<ChartConfig> = {
  showLegend: undefined,
  showGrid: undefined,
  smooth: undefined,
  showMarkers: undefined,
  stacked100: undefined,
  palette: undefined,
  yScale: undefined,
  sortDir: undefined,
  xTitle: undefined,
  yTitle: undefined,
  areaOpacity: undefined,
  referenceValue: undefined,
  border: undefined,
  radius: undefined,
  shadow: undefined,
}
function resetStyle(): void {
  emit('update:config', { ...props.config, ...STYLE_DEFAULTS })
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

// The AI output block (Explain / Recommend) lives at the bottom of the chart settings drawer
// body. When it appears, scroll the drawer so the user sees the narrative/recommendation
// without hunting for it — this is what makes the "Explain" toggle visibly deliver the
// definition right under the action button.
const aiOutputEl = ref<HTMLElement | null>(null)
watch(
  () => explainText.value ?? recommendPanel.value,
  (v) => {
    if (!v) return
    // flush:'post' so the v-if AI output block is mounted (and the ref is bound) before we
    // try to scroll it; otherwise the ref is still null and the scroll is skipped.
    void nextTick(() => aiOutputEl.value?.scrollIntoView({ behavior: 'smooth', block: 'end' }))
  },
  { flush: 'post' },
)

const sectionCls = 'border-b border-outline-gray-1 last:border-b-0'
const summaryCls = 'cursor-pointer px-4 py-3 text-[11px] font-bold uppercase tracking-wider text-ink-gray-9 hover:bg-surface-gray-1 transition-colors select-none marker:text-primary-5'
const sectionBodyCls = 'px-4 pb-4 pt-1 flex flex-col gap-3.5'
const selectCls = 'w-full rounded-3 border border-outline-gray-2 bg-white px-2.5 py-1.5 text-xs font-medium text-ink-gray-8 shadow-sm transition-all hover:border-primary-4 focus:border-primary-5 focus:outline-none focus:ring-1 focus:ring-primary-5'
const labelCls = 'mb-1.5 block text-[11px] font-semibold text-ink-gray-5 uppercase tracking-wide'
const toggleCls = 'flex items-center justify-between gap-1 rounded-3 border border-outline-gray-1 bg-surface-gray-1 px-3 py-2 text-xs font-medium text-ink-gray-7 shadow-sm transition-all hover:bg-white hover:border-outline-gray-2'

function handleSlicerChange(e: Event): void {
  const val = (e.target as HTMLSelectElement).value
  if (!val) {
    if (props.activeKey !== undefined) emit('select', props.activeKey)
    return
  }
  // Map string back to original key type
  const rawKey = props.data?.keys.find(k => String(k) === val)
  if (rawKey !== undefined) {
    emit('select', rawKey)
  }
}

// Suppress TS unused warnings
console.log(exportPng, explainThisChart, recommend);
</script>

<template>
  <div
    :class="[cardClass, selected ? 'ring-2 ring-primary' : '']"
    :style="config.bg ? { backgroundColor: config.bg } : undefined"
    @click="emit('open-settings')"
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
          :class="config.bold ? 'text-base font-bold text-ink-gray-9' : ''"
          :placeholder="autoTitle"
          @keydown.enter="confirmTitle"
          @keydown.esc="cancelTitle"
          @blur="confirmTitle"
        />
        <template v-else>
          <span class="cursor-move truncate" :class="config.bold ? 'text-base font-bold text-ink-gray-9' : 'text-sm font-semibold text-ink-gray-8'" :title="title">{{ title }}</span>
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

      <Teleport to="#tile-settings-drawer-body">
      <div v-if="selected" class="js-export-exclude flex flex-col gap-3">
        <!-- LIVE TITLE PREVIEW: the Bold toggle (and Colour) is now visibly effective right
             inside the pane, not only on the far-away canvas tile. -->
        <div class="rounded-2 border border-outline-gray-2 bg-surface-base px-3 py-2">
          <p class="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-gray-4">Title preview</p>
          <p class="truncate" :class="config.bold ? 'text-base font-bold text-ink-gray-9' : 'text-sm font-medium text-ink-gray-8'" :title="title">{{ title }}</p>
        </div>
        <!-- Full picker strip -->
        <template v-if="!config.hideControls || selected">
          <!-- 1. DATA MAPPING -->
          <details class="group" :class="sectionCls" open>
            <summary :class="summaryCls">Data & Mapping</summary>
            <div :class="sectionBodyCls">
              <div>
                <label :class="labelCls">Chart Type</label>
                <select :class="selectCls" :value="config.chartType" @change="onTypeChange(($event.target as HTMLSelectElement).value)">
                  <option v-for="t in CHART_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
                </select>
              </div>
              <div>
                <label :class="labelCls">{{ axisLabels.dim }}</label>
                <select :class="selectCls" :value="config.dimension ?? ''" @change="onDimensionChange(($event.target as HTMLSelectElement).value)">
                  <option value="">— none —</option>
                  <option v-for="c in dimOptions" :key="c.name" :value="c.name">{{ c.name }}</option>
                </select>
              </div>
              <div v-if="showBreakdown">
                <label :class="labelCls">{{ axisLabels.series }}</label>
                <select :class="selectCls" :value="config.series ?? ''" :disabled="!config.dimension" @change="onSeriesChange(($event.target as HTMLSelectElement).value)">
                  <option value="">— none —</option>
                  <option v-for="c in seriesOptions" :key="c.name" :value="c.name">{{ c.name }}</option>
                </select>
              </div>
              <div>
                <label :class="labelCls">{{ axisLabels.measure }}</label>
                <select :class="selectCls" :value="config.measure ?? ''" @change="onMeasureChange(($event.target as HTMLSelectElement).value)">
                  <option value="">Count of rows</option>
                  <option v-for="c in columns" :key="c.name" :value="c.name">{{ c.name }}</option>
                </select>
              </div>
              <div v-if="showYMeasure">
                <label :class="labelCls">{{ axisLabels.measureY ?? 'Y axis' }}</label>
                <select :class="selectCls" :value="config.measureY ?? ''" @change="onMeasureYChange(($event.target as HTMLSelectElement).value)">
                  <option value="">— numeric column —</option>
                  <option v-for="c in yMeasureOptions" :key="c.name" :value="c.name">{{ c.name }}</option>
                </select>
              </div>
              <div v-if="config.measure !== null && config.chartType !== 'slicer'">
                <label :class="labelCls">Aggregation</label>
                <select :class="selectCls" :value="config.aggregation" @change="onAggChange(($event.target as HTMLSelectElement).value)">
                  <option v-for="a in aggOptions" :key="a" :value="a">{{ AGG_LABEL[a] }}</option>
                </select>
              </div>
              <div v-if="config.dimension && config.chartType !== 'slicer'">
                <label :class="labelCls">Show top</label>
                <div class="flex items-center gap-1">
                  <input type="number" min="1" :max="TOPN_MAX" inputmode="numeric" :class="[selectCls, 'w-20']" :value="config.topN ?? ''" :placeholder="String(DEFAULT_TOPN)" :title="`Top categories to show (max ${TOPN_MAX})`" @change="onTopNInput(($event.target as HTMLInputElement).value)" />
                  <button v-for="p in TOPN_PRESETS" :key="p.label" type="button" class="rounded-3 border px-2 py-1.5 text-[11px] font-semibold shadow-sm transition-all" :class="config.topN === p.value ? 'border-primary-5 bg-primary-5 text-white' : 'border-outline-gray-2 bg-white text-ink-gray-7 hover:border-primary-4 hover:text-primary-6'" :title="p.label === 'All' ? `Show up to ${TOPN_MAX}` : `Show top ${p.value}`" @click="setTopN(p.value)">{{ p.label }}</button>
                </div>
              </div>
              <div v-if="config.chartType !== 'slicer'">
                <label :class="labelCls">Sort Order</label>
                <select :class="selectCls" :value="config.sortDir ?? 'auto'" @change="patch({ sortDir: (($event.target as HTMLSelectElement).value) as ChartConfig['sortDir'] })">
                  <option value="auto">Auto</option>
                  <option value="desc">↓ Highest to Lowest</option>
                  <option value="asc">↑ Lowest to Highest</option>
                  <option value="alpha">A—Z Alphabetical</option>
                </select>
              </div>
            </div>
          </details>

          <!-- 2. AXES & LEGEND -->
          <details class="group" :class="sectionCls" v-if="config.chartType !== 'slicer' && (isCartesian || canLegend)">
            <summary :class="summaryCls">Axes & Legend</summary>
            <div :class="sectionBodyCls">
              <div v-if="isCartesian" class="grid grid-cols-2 gap-2">
                <div>
                  <label :class="labelCls">X Axis Title</label>
                  <input type="text" :class="selectCls" :value="config.xTitle ?? ''" placeholder="(auto)" @change="patch({ xTitle: (($event.target as HTMLInputElement).value).trim() || null })" />
                </div>
                <div>
                  <label :class="labelCls">Y Axis Title</label>
                  <input type="text" :class="selectCls" :value="config.yTitle ?? ''" placeholder="(auto)" @change="patch({ yTitle: (($event.target as HTMLInputElement).value).trim() || null })" />
                </div>
              </div>
              <div v-if="isCartesian">
                <label :class="labelCls">Y Scale</label>
                <select :class="selectCls" :value="config.yScale ?? 'linear'" @change="patch({ yScale: (($event.target as HTMLSelectElement).value) as 'linear' | 'log' })">
                  <option value="linear">Linear Scale</option>
                  <option value="log">Logarithmic Scale</option>
                </select>
              </div>
              <div class="grid grid-cols-2 gap-2">
                <label v-if="canLegend" :class="toggleCls">
                  <span>Legend</span>
                  <input type="checkbox" class="h-4 w-4 rounded-sm border-outline-gray-3 text-primary-5 focus:ring-primary-5 cursor-pointer" :checked="config.showLegend !== false" @change="patch({ showLegend: ($event.target as HTMLInputElement).checked })" />
                </label>
                <label v-if="isCartesian" :class="toggleCls">
                  <span>Gridlines</span>
                  <input type="checkbox" class="h-4 w-4 rounded-sm border-outline-gray-3 text-primary-5 focus:ring-primary-5 cursor-pointer" :checked="config.showGrid !== false" @change="patch({ showGrid: ($event.target as HTMLInputElement).checked })" />
                </label>
              </div>
              <div class="grid grid-cols-2 gap-2" v-if="isLine || canStack">
                <label v-if="isLine" :class="toggleCls">
                  <span>Smooth Curve</span>
                  <input type="checkbox" class="h-4 w-4 rounded-sm border-outline-gray-3 text-primary-5 focus:ring-primary-5 cursor-pointer" :checked="config.smooth !== false" @change="patch({ smooth: ($event.target as HTMLInputElement).checked })" />
                </label>
                <label v-if="isLine" :class="toggleCls">
                  <span>Point Markers</span>
                  <input type="checkbox" class="h-4 w-4 rounded-sm border-outline-gray-3 text-primary-5 focus:ring-primary-5 cursor-pointer" :checked="config.showMarkers !== false" @change="patch({ showMarkers: ($event.target as HTMLInputElement).checked })" />
                </label>
                <label v-if="config.series && canStack" :class="toggleCls">
                  <span>100% Stacked</span>
                  <input type="checkbox" class="h-4 w-4 rounded-sm border-outline-gray-3 text-primary-5 focus:ring-primary-5 cursor-pointer" :checked="config.stacked100 === true" @change="patch({ stacked100: ($event.target as HTMLInputElement).checked })" />
                </label>
              </div>
            </div>
          </details>

          <!-- 3. TYPOGRAPHY & COLORS -->
          <details class="group" :class="sectionCls">
            <summary :class="summaryCls">Typography & Colors</summary>
            <div :class="sectionBodyCls">
              <div class="grid grid-cols-2 gap-2">
                <div>
                  <label :class="labelCls">Font Family</label>
                  <select :class="selectCls" :value="config.fontFamily ?? ''" @change="patch({ fontFamily: (($event.target as HTMLSelectElement).value) || null })">
                    <option value="">Geist (Default)</option>
                    <option value="'Plus Jakarta Sans', sans-serif">Plus Jakarta Sans</option>
                    <option value="'Inter', sans-serif">Inter</option>
                    <option value="'Poppins', sans-serif">Poppins</option>
                    <option value="'Montserrat', sans-serif">Montserrat</option>
                    <option value="'Roboto', sans-serif">Roboto</option>
                    <option value="'Fira Code', monospace">Fira Code</option>
                    <option value="Arial, sans-serif">Arial</option>
                    <option value="'Times New Roman', serif">Times New Roman</option>
                  </select>
                </div>
                <div>
                  <label :class="labelCls">Font Size</label>
                  <select :class="selectCls" :value="config.valueFontSize ?? ''" @change="patch({ valueFontSize: numOrNull(($event.target as HTMLSelectElement).value) })">
                    <option value="">Default (11px)</option>
                    <option value="10">10px</option>
                    <option value="12">12px</option>
                    <option value="14">14px</option>
                    <option value="16">16px</option>
                    <option value="18">18px</option>
                    <option value="20">20px</option>
                    <option value="24">24px</option>
                  </select>
                </div>
              </div>
              <div>
                <label :class="labelCls">Color Palette</label>
                <select :class="selectCls" :value="config.palette ?? ''" @change="patch({ palette: (($event.target as HTMLSelectElement).value) || null })">
                  <option value="">Spencer Theme (Default)</option>
                  <option v-for="p in CHART_PALETTES" :key="p.id" :value="p.id">{{ p.label }}</option>
                </select>
              </div>
              <div v-if="isArea || config.chartType === 'heatmap'">
                <label :class="labelCls">Area Fill Opacity</label>
                <input type="number" min="0" max="1" step="0.05" :class="selectCls" :value="config.areaOpacity ?? ''" placeholder="0.2 (Default)" @change="patch({ areaOpacity: clampPct(($event.target as HTMLInputElement).value) })" />
              </div>
            </div>
          </details>

          <!-- 4. TILE STYLING -->
          <details class="group" :class="sectionCls">
            <summary :class="summaryCls">Card Style</summary>
            <div :class="sectionBodyCls">
              <div class="grid grid-cols-2 gap-2">
                <label :class="toggleCls">
                  <span>Border</span>
                  <input type="checkbox" class="h-4 w-4 rounded-sm border-outline-gray-3 text-primary-5 focus:ring-primary-5 cursor-pointer" :checked="config.border !== false" @change="patch({ border: ($event.target as HTMLInputElement).checked })" />
                </label>
                <label :class="toggleCls">
                  <span>Shadow</span>
                  <input type="checkbox" class="h-4 w-4 rounded-sm border-outline-gray-3 text-primary-5 focus:ring-primary-5 cursor-pointer" :checked="config.shadow === true" @change="patch({ shadow: ($event.target as HTMLInputElement).checked })" />
                </label>
              </div>
              <div>
                <label :class="labelCls">Corner Radius</label>
                <select :class="selectCls" :value="config.radius ?? 'md'" @change="patch({ radius: (($event.target as HTMLSelectElement).value) as ChartConfig['radius'] })">
                  <option value="sm">Small</option>
                  <option value="md">Medium (Default)</option>
                  <option value="lg">Large</option>
                </select>
              </div>
              
              <button type="button" class="mt-2 w-full rounded-3 border border-outline-gray-2 bg-white px-2 py-1.5 text-xs font-semibold text-ink-gray-6 shadow-sm transition-all hover:border-outline-gray-3 hover:bg-surface-gray-1 hover:text-ink-gray-8" @click="resetStyle">
                Reset Style to Default
              </button>
            </div>
          </details>
        </template>
<!-- Presentation toolbar (#3/#4/#5 + remove). Always available so a cleaned tile can
             be recoloured / restored; itself js-export-exclude, so present/export hide it. -->
        <!-- Presentation format toggles: compact segmented bar, active state in brand colour.
             Always available so a cleaned tile can be recoloured / restored. -->
        <div class="flex items-center gap-1">
          <button
            type="button"
            class="flex-1 rounded-2 border border-outline-gray-2 bg-surface-base p-1.5 text-ink-gray-6 transition-colors hover:bg-surface-gray-2"
            :class="config.color || config.bg ? 'text-primary' : 'text-ink-gray-6 hover:text-primary'"
            title="Colour &amp; card background"
            @click="toggleColor"
          >
            <Palette class="mx-auto h-4 w-4" />
          </button>
          <button
            type="button"
            class="flex-1 rounded-2 border border-outline-gray-2 bg-surface-base p-1.5 text-ink-gray-6 transition-colors hover:bg-surface-gray-2"
            :class="config.bold ? 'text-primary' : 'text-ink-gray-6 hover:text-primary'"
            :title="config.bold ? 'Unbold title' : 'Bold title'"
            @click="toggleBold"
          >
            <Bold class="mx-auto h-4 w-4" />
          </button>
          <button
            type="button"
            class="flex-1 rounded-2 border border-outline-gray-2 bg-surface-base p-1.5 text-ink-gray-6 transition-colors hover:bg-surface-gray-2"
            :class="config.showValues ? 'text-primary' : 'text-ink-gray-6 hover:text-primary'"
            :title="config.showValues ? 'Hide values on chart' : 'Show values on chart'"
            @click="toggleValues"
          >
            <ListOrdered class="mx-auto h-4 w-4" />
          </button>
          <button
            type="button"
            class="flex-1 rounded-2 border border-outline-gray-2 bg-surface-base p-1.5 text-ink-gray-6 transition-colors hover:bg-surface-gray-2"
            :class="config.hideControls ? 'text-primary' : 'text-ink-gray-6 hover:text-primary'"
            :title="config.hideControls ? 'Show controls' : 'Hide controls (keep title + chart)'"
            @click="toggleClean"
          >
            <SlidersHorizontal class="mx-auto h-4 w-4" />
          </button>
        </div>
        <div class="flex items-center gap-1">
          <button
            type="button"
            class="flex-1 rounded-2 border border-outline-gray-2 bg-surface-base p-1.5 text-ink-gray-4 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-7"
            title="Duplicate chart"
            @click="emit('duplicate')"
          >
            <Copy class="mx-auto h-4 w-4" />
          </button>
          <button
            type="button"
            class="flex-1 rounded-2 border border-outline-gray-2 bg-surface-base p-1.5 text-ink-gray-4 transition-colors hover:bg-surface-gray-2 hover:text-ink-red"
            title="Remove chart"
            @click="emit('remove')"
          >
            <X class="mx-auto h-4 w-4" />
          </button>
        </div>

        <!-- AI OUTPUT (Explain / Recommend) — rendered right under the Actions, as requested,
             and always visible (not gated by the clean/controls toggle). -->
        <div
          ref="aiOutputEl"
          v-if="recommendPanel || recommendError || explainText || explainError"
          class="space-y-2 rounded-2 border border-outline-gray-2 bg-primary-1/50 px-2.5 py-2 text-sm"
        >
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
      </div>
  </Teleport>
    </div>

    <!-- TASK-033/036 colour popover (ResultsTable menuOpen + fixed-backdrop idiom). Two
         targets — series colour + card background — each with presets, a native any-colour
         picker, a hex field, and a reset. `.no-drag` keeps the floating panel from starting a
         tile drag. Picking does NOT close the panel, so both sections stay usable.
         Teleported into the drawer body so it sits ABOVE the drawer (otherwise it paints behind
         the z-50 <aside> and becomes unclickable). -->
    <Teleport to="#tile-settings-drawer-body">
    <template v-if="colorOpen">
      <div class="js-export-exclude no-drag fixed inset-0 z-40" @click="colorOpen = false"></div>
      <div
        class="js-export-exclude no-drag fixed z-50 w-56 overflow-auto rounded-3 border border-outline-gray-2 bg-surface-base p-2.5 shadow-lg"
        :style="{ top: `${colorPos.y}px`, left: `${colorPos.x}px`, maxHeight: `${colorMaxH}px`, transform: 'translateX(-100%)' }"
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
    </Teleport>

    <!-- AI output (Explain / Recommend) is now rendered inside the chart settings drawer body,
         directly under the Actions, so it is always visible where the user expects it. -->

    <!-- Plot. The canvas host is always mounted so ECharts has a stable element to
         init into; transient states are overlaid rather than replacing it. `flex-1 min-h-0`
         lets the plot fill the tile's remaining height (TASK-034 resizable tiles) — the
         useEchart ResizeObserver re-renders ECharts when this box changes. `.no-drag` keeps
         grid drag from starting on the canvas. A plain click anywhere on the tile (including
         the plot) bubbles to the root and opens the settings drawer; ECharts' own listener
         still fires the cross-filter independently, so both behaviours coexist. -->
    <div class="no-drag relative min-h-0 flex-1 p-2">
        <div v-if="config.chartType === 'slicer'" class="flex h-full w-full flex-col justify-center px-4">
          <label class="mb-1.5 block text-[11px] font-bold uppercase tracking-wider text-ink-gray-5 text-center">Filter {{ config.dimension || 'Column' }}</label>
          <select
            class="w-full cursor-pointer rounded-3 border border-outline-gray-2 bg-surface-base px-3 py-2 text-sm font-medium text-ink-gray-8 shadow-sm transition-colors hover:border-primary-4 focus:border-primary-5 focus:outline-none focus:ring-1 focus:ring-primary-5"
            :value="activeKey === undefined ? '' : String(activeKey)"
            @change="handleSlicerChange"
            @click.stop
          >
            <option value="">All</option>
            <option v-for="key in (data?.keys || [])" :key="String(key)" :value="String(key)">
              {{ String(key) }}
            </option>
          </select>
        </div>
        <div v-else ref="chartEl" class="h-full w-full"></div>

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
