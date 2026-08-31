<script setup lang="ts">
// One KPI card. Presentation + its own inline editor; it does NOT fetch. ChartCanvas
// owns all data orchestration and passes the result down, so every tile's loading /
// error state is handled uniformly in one place.
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  AlertCircle,
  Bold,
  Copy,
  GripVertical,
  Loader2,
  Minus,
  Palette,
  SlidersHorizontal,
  TrendingDown,
  TrendingUp,
  X,
} from '@lucide/vue'
import type {
  Aggregation,
  AggregateResponse,
  AggregateValue,
  ColumnMeta,
  KpiConfig,
  KpiTargetMode,
} from '../types'
import { AGG_LABEL, allowedAggregations, coerceAggregation } from '../utils/aggregations'
import { temporalColumns } from '../utils/columnKind'
import { asHexInput, CHART_BG_PALETTE, CHART_PALETTE, normalizeHex } from '../utils/chartPalette'
import { effectiveColor, formatNumber, type NumberOverrides } from '../composables/useDashboardSettings'

const props = defineProps<{
  config: KpiConfig
  columns: ColumnMeta[]
  loading: boolean
  error: string | null
  value: AggregateValue
  // TASK-031: the metric-over-time series for the sparkline (ChartCanvas fetches it,
  // exactly like `value`). Null when this card has no trend dimension or none loaded yet.
  trend?: AggregateResponse | null
  // True while this card's editor is shown in the side drawer (Power BI–style). When false
  // the inline controls are hidden so the card stays clean; when true they teleport to the drawer.
  selected?: boolean
}>()

const emit = defineEmits<{
  'update:config': [config: KpiConfig]
  remove: [id: number]
  duplicate: [id: number]
  // The card body was clicked — ChartCanvas opens this card's settings in the side drawer.
  'open-settings': []
}>()

// The auto-derived label ("Sum of revenue" / "Total rows"); the user can override it
// (TASK-033 #2) via the editor's Title field. `title` is what everything else consumes.
const autoTitle = computed(() =>
  props.config.measure === null
    ? 'Total rows'
    : `${AGG_LABEL[props.config.aggregation]} of ${props.config.measure}`,
)
const title = computed(() => props.config.title?.trim() || autoTitle.value)

const aggOptions = computed(() => allowedAggregations(props.columns, props.config.measure))

// A dropped/renamed column leaves a config pointing at nothing. The server answers
// with a 400 (surfaced via `error`); flag it here so the card invites a fix.
const missingColumn = computed(
  () =>
    props.config.measure !== null &&
    !props.columns.some((c) => c.name === props.config.measure),
)

// TASK-044: per-KPI number formatting overrides (null ⇒ global setting).
const kpiFmt = computed<NumberOverrides>(() => ({
  decimals: props.config.decimals,
  thousands: props.config.thousands,
  currency: props.config.currency,
}))

// The value as a finite number, or null — declared before the count-up tween below.
const numericValue = computed<number | null>(() => {
  const v = props.value
  return typeof v === 'number' && Number.isFinite(v) ? v : null
})

// TASK-045: animate the big number with a count-up (easeOutCubic) whenever the value
// changes — loads, cross-filter refreshes, target edits all get a smooth roll. Respects
// prefers-reduced-motion; non-numeric values (dates / null) skip the tween.
const reduceMotion =
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

const animated = ref<number>(
  typeof props.value === 'number' && Number.isFinite(props.value) ? props.value : 0,
)
let countRaf = 0
watch(
  numericValue,
  (to, from) => {
    const target = typeof to === 'number' && Number.isFinite(to) ? to : 0
    const start = typeof from === 'number' && Number.isFinite(from) ? from : 0
    if (reduceMotion || start === target) {
      cancelAnimationFrame(countRaf)
      animated.value = target
      return
    }
    const duration = 650
    const t0 = performance.now()
    cancelAnimationFrame(countRaf)
    const step = (now: number): void => {
      const p = Math.min(1, (now - t0) / duration)
      const eased = 1 - Math.pow(1 - p, 3)
      animated.value = start + (target - start) * eased
      if (p < 1) countRaf = requestAnimationFrame(step)
      else animated.value = target
    }
    countRaf = requestAnimationFrame(step)
  },
  { immediate: true },
)
onBeforeUnmount(() => cancelAnimationFrame(countRaf))

const display = computed(() => {
  const v = props.value
  if (v === null) return '—'
  if (typeof v === 'string') return v // MIN/MAX over a date arrives as an ISO string
  if (!Number.isFinite(v)) return '—'
  const num = formatNumber(animated.value, kpiFmt.value)
  const prefix = props.config.prefix ?? ''
  const suffix = props.config.suffix ?? ''
  return `${prefix}${num}${suffix}`
})

// --- #14 delta vs target ----------------------------------------------------------
function fmtNum(n: number): string {
  return formatNumber(n, kpiFmt.value)
}

// The card's value text colour: when `colorByTarget` is on, the value takes the delta's
// good/bad hue (the same design tokens the delta chip uses -- --ink-green-7 / --ink-red-6,
// not a one-off literal); otherwise a tile accent first, then the global accent, else default ink.
const valueColorStyle = computed(() => {
  if (props.config.colorByTarget) {
    const d = delta.value
    if (d) return { color: d.good ? 'var(--ink-green-7)' : 'var(--ink-red-6)' }
  }
  const c = effectiveColor(props.config.accent)
  return c ? { color: c } : undefined
})

// TASK-044: alignment of the label + value block (left by default, or centered).
const alignCls = computed(() =>
  props.config.align === 'center' ? 'items-center text-center' : '',
)

const hasTarget = computed(() => props.config.target !== null && props.config.target !== undefined)

// The delta of the (possibly cross-filtered) value against the card's target. Null unless
// there IS a target AND the value is a finite number — the chip renders only when non-null.
const delta = computed(() => {
  const target = props.config.target
  const v = numericValue.value
  if (target === null || target === undefined || v === null) return null
  const diff = v - target
  const mode: KpiTargetMode = props.config.targetMode ?? 'higher_better'
  const good = mode === 'higher_better' ? diff >= 0 : diff <= 0
  // % vs target is undefined when target is 0 — the chip falls back to the absolute gap.
  const pct = target !== 0 ? (diff / Math.abs(target)) * 100 : null
  return { diff, pct, good, flat: diff === 0 }
})

const deltaIcon = computed(() => {
  const d = delta.value
  if (!d || d.flat) return Minus
  return d.diff > 0 ? TrendingUp : TrendingDown
})

const deltaColorCls = computed(() => {
  const d = delta.value
  if (!d) return ''
  if (d.flat) return 'text-ink-gray-5'
  return d.good ? 'text-ink-green' : 'text-ink-red'
})

const deltaText = computed(() => {
  const d = delta.value
  if (!d) return ''
  return d.pct !== null ? `${fmtNum(Math.abs(d.pct))}%` : fmtNum(Math.abs(d.diff))
})

const targetDisplay = computed(() =>
  props.config.target === null || props.config.target === undefined
    ? ''
    : fmtNum(props.config.target),
)

const deltaTitle = computed(() => {
  const d = delta.value
  if (!d) return ''
  if (d.flat) return `On target (${targetDisplay.value})`
  return `${deltaText.value} ${d.diff > 0 ? 'above' : 'below'} target (${targetDisplay.value})`
})

// --- #14 part 2: trend sparkline --------------------------------------------------
// The finite-number series from the trend aggregate, in the chronological order the
// server returned (temporal dimensions sort ascending). Non-numeric values (MIN/MAX
// over a date ⇒ ISO strings) and nulls are dropped, so a sparkline is drawn only when
// the metric is genuinely numeric.
const trendValues = computed<number[]>(() => {
  const vals = props.trend?.values
  if (!vals) return []
  return vals.filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
})

// SVG polyline points in a fixed 0..100 x 0..24 viewBox. Null unless there are >=2
// points to join. `preserveAspectRatio="none"` stretches it to the card width; the
// stroke stays crisp via vector-effect. A flat series (max == min) draws a mid-line.
const SPARK_W = 100
const SPARK_H = 24
const SPARK_PAD = 2
const sparkPoints = computed<string | null>(() => {
  const v = trendValues.value
  const n = v.length
  if (n < 2) return null
  const min = Math.min(...v)
  const max = Math.max(...v)
  const flat = max === min
  const span = max - min
  const innerW = SPARK_W - 2 * SPARK_PAD
  const innerH = SPARK_H - 2 * SPARK_PAD
  return v
    .map((val, i) => {
      const x = SPARK_PAD + (i / (n - 1)) * innerW
      // A flat series (all values equal) has no range to normalize against; draw it as a
      // centered horizontal line rather than pinning every point to the axis floor.
      const y = flat ? SPARK_H / 2 : SPARK_PAD + (1 - (val - min) / span) * innerH
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
})

// TASK-044: alternative sparkline shapes. `area` closes the line down to the baseline;
// `bar` draws a mini bar chart; `line` (default) is the polyline above.
const sparkPolygon = computed<string | null>(() => {
  const p = sparkPoints.value
  if (!p) return null
  return `0,${SPARK_H} ${p} ${SPARK_W},${SPARK_H}`
})
const sparkBars = computed<Array<{ x: number; y: number; w: number; h: number }> | null>(() => {
  const v = trendValues.value
  const n = v.length
  if (n < 1) return null
  const min = Math.min(...v)
  const max = Math.max(...v)
  const span = max - min || 1
  const innerW = SPARK_W
  const innerH = SPARK_H - 2 * SPARK_PAD
  const slot = innerW / n
  const bw = slot * 0.7
  return v.map((val, i) => {
    const h = ((val - min) / span) * innerH
    return { x: i * slot + (slot - bw) / 2, y: SPARK_H - SPARK_PAD - h, w: bw, h }
  })
})

// Long-form title: the metric, the time column, and the span it covers.
const sparkTitle = computed(() => {
  const t = props.trend
  const n = trendValues.value.length
  if (!t || n < 2) return ''
  const dim = t.dimension ?? 'time'
  return `${title.value} by ${dim}: ${n} points, ${String(t.keys[0])} → ${String(t.keys[t.keys.length - 1])}`
})

// Temporal columns are the only valid trend axes; when there are none the picker hides.
const trendOptions = computed(() => temporalColumns(props.columns))

// `''` is the select's stand-in for null (COUNT(*)) -- <option> values are strings.
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

// A target is display-only (no query change), so ChartCanvas won't refetch on these.
function onTargetChange(raw: string): void {
  const trimmed = raw.trim()
  const parsed = trimmed === '' ? null : Number(trimmed)
  const target = parsed !== null && Number.isFinite(parsed) ? parsed : null
  emit('update:config', {
    ...props.config,
    target,
    // First time a target is set, give the chip a direction; clearing it leaves the
    // (now-inert) mode untouched so re-adding a target keeps the user's last choice.
    targetMode: target !== null ? (props.config.targetMode ?? 'higher_better') : props.config.targetMode,
  })
}

function onTargetModeChange(raw: string): void {
  emit('update:config', { ...props.config, targetMode: raw as KpiTargetMode })
}

// Trend has its OWN aggregate (grouped by the temporal column), independent of the
// scalar, so ChartCanvas refetches only the trend on this change -- never the value.
function onTrendChange(raw: string): void {
  emit('update:config', { ...props.config, trendDimension: raw === '' ? null : raw })
}

// --- TASK-033 presentation controls (title / accent / clean) ----------------------
// Emit the RAW text (only all-whitespace collapses to null) so interior spaces in a
// multi-word title ("New York sales") survive; `title` trims for display/consumption.
function onTitleChange(raw: string): void {
  emit('update:config', { ...props.config, title: raw.trim() === '' ? null : raw })
}

// Accent colour popover — ResultsTable's `menuOpen` + fixed-backdrop idiom (no document
// listeners). `null` restores the brand primary. Drives the sparkline stroke via currentColor.
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
  let top = r.bottom + 4
  if (top + estH > vh - margin) top = Math.max(margin, r.top - estH - 4)
  colorPos.value = { x: r.right, y: top }
  colorMaxH.value = Math.max(160, Math.min(estH, vh - top - margin))
  colorOpen.value = true
}
function pickColor(c: string | null): void {
  // Do NOT close the popover — it now carries two sections (accent + card background), so a
  // single pick should leave both usable; the backdrop click closes it.
  if (c !== (props.config.accent ?? null)) emit('update:config', { ...props.config, accent: c })
}
function onAccentHex(raw: string): void {
  const v = raw.trim()
  if (v === '') return pickColor(null)
  const hex = normalizeHex(v)
  if (hex) pickColor(hex) // ignore an unparseable entry (the field reverts to the shown value)
}
// TASK-036: per-card background fill. null ⇒ the default surface.
function pickBg(c: string | null): void {
  if (c !== (props.config.bg ?? null)) emit('update:config', { ...props.config, bg: c })
}
function onBgHex(raw: string): void {
  const v = raw.trim()
  if (v === '') return pickBg(null)
  const hex = normalizeHex(v)
  if (hex) pickBg(hex)
}
// TASK-036: bold the title AND the big value.
function toggleBold(): void {
  emit('update:config', { ...props.config, bold: !props.config.bold })
}

// TASK-037: the metric editor lives in the side settings drawer (Power BI–style) when the card
// is selected, so it always opens at full size regardless of how small (or where) the card is.


function toggleClean(): void {
  emit('update:config', { ...props.config, hideControls: !props.config.hideControls })
}

// TASK-044: generic config patch + number parse + style reset for the drawer controls.
function patch(p: Partial<KpiConfig>): void {
  emit('update:config', { ...props.config, ...p })
}
function numOrNull(raw: string): number | null {
  const s = raw.trim()
  if (s === '') return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}
const STYLE_DEFAULTS: Partial<KpiConfig> = {
  decimals: undefined,
  thousands: undefined,
  currency: undefined,
  prefix: undefined,
  suffix: undefined,
  colorByTarget: undefined,
  showSpark: undefined,
  sparkType: undefined,
  align: undefined,
  border: undefined,
  radius: undefined,
  shadow: undefined,
}
function resetStyle(): void {
  emit('update:config', { ...props.config, ...STYLE_DEFAULTS })
}

// TASK-044: per-card chrome driven by config (border / corner radius / drop shadow).
const cardClass = computed(() => {
  const r = props.config.radius ?? 'md'
  const radius = r === 'sm' ? 'rounded-3' : r === 'lg' ? 'rounded-6' : 'rounded-5'
  const border = props.config.border === false ? 'border-0' : 'border border-outline-gray-1 shadow-sm'
  const shadow = props.config.shadow === false ? '' : 'hover:shadow-md hover:-translate-y-0.5 transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]'
  return `group tile-drag-handle relative flex h-full flex-col overflow-hidden bg-surface-base p-4 ${radius} ${border} ${shadow}`
})

const selectCls =
  'w-full rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-1 text-xs text-ink-gray-8 focus:border-primary-5 focus:outline-none'
</script>

<template>
  <div
    :class="[cardClass, selected ? 'ring-2 ring-primary' : '']"
    @click="emit('open-settings')"
    :style="config.bg ? { backgroundColor: config.bg } : undefined"
  >
    <!-- Label + hover actions -->
    <div class="flex items-start justify-between gap-2">
      <div class="flex min-w-0 items-center gap-1">
        <!-- Drag grip: a visible "you can move this" affordance. TASK-036 made the whole
             card root the `.tile-drag-handle`, so a drag can start anywhere on the tile that
             isn't an interactive control — the grip just advertises it. Hidden in present/export. -->
        <span
          class="tile-drag-handle js-export-exclude -ml-0.5 flex shrink-0 cursor-grab items-center text-ink-gray-3 opacity-0 transition-opacity hover:text-ink-gray-6 group-hover:opacity-100 active:cursor-grabbing"
          title="Drag to move"
        >
          <GripVertical class="h-3.5 w-3.5" />
        </span>
        <span
          class="cursor-move truncate text-xs uppercase tracking-wide text-ink-gray-5"
          :class="config.bold ? 'font-bold' : 'font-medium'"
          :title="title"
        >
          {{ title }}
        </span>
      </div>
      <Teleport to="#tile-settings-drawer-body">
      <div v-if="selected" class="js-export-exclude flex flex-col gap-2">
        <!-- Presentation toolbar (colour / bold / clean / remove) — lives in the settings
             drawer while this card is selected; hidden on the card itself. -->
        <button
          type="button"
          class="flex items-center gap-2 rounded-2 px-2 py-1.5 text-left text-xs hover:bg-surface-gray-2"
          :class="config.accent || config.bg ? 'text-primary' : 'text-ink-gray-7'"
          title="Colour & card background"
          @click="toggleColor"
        >
          <Palette class="h-3.5 w-3.5" /> Colour &amp; background
        </button>
        <button
          type="button"
          class="flex items-center gap-2 rounded-2 px-2 py-1.5 text-left text-xs hover:bg-surface-gray-2"
          :class="config.bold ? 'text-primary' : 'text-ink-gray-7'"
          :title="config.bold ? 'Unbold title & value' : 'Bold title & value'"
          @click="toggleBold"
        >
          <Bold class="h-3.5 w-3.5" /> Bold
        </button>
        <button
          type="button"
          class="flex items-center gap-2 rounded-2 px-2 py-1.5 text-left text-xs hover:bg-surface-gray-2"
          :class="config.hideControls ? 'text-primary' : 'text-ink-gray-7'"
          :title="config.hideControls ? 'Show controls' : 'Hide controls (keep title + value)'"
          @click="toggleClean"
        >
          <SlidersHorizontal class="h-3.5 w-3.5" /> Clean
        </button>
        <button
          type="button"
          class="flex items-center gap-2 rounded-2 px-2 py-1.5 text-left text-xs text-ink-gray-7 hover:bg-surface-gray-2 hover:text-ink-red"
          title="Remove card"
          @click="emit('remove', config.id)"
        >
          <X class="h-3.5 w-3.5" /> Remove
        </button>
        <button
          type="button"
          class="flex items-center gap-2 rounded-2 px-2 py-1.5 text-left text-xs text-ink-gray-7 hover:bg-surface-gray-2"
          title="Duplicate card"
          @click="emit('duplicate', config.id)"
        >
          <Copy class="h-3.5 w-3.5" /> Duplicate
        </button>
      </div>
      </Teleport>
    </div>

    <!-- Value + #14 delta-vs-target chip -->
    <div class="mt-2 flex min-h-[2.25rem] items-center" :class="alignCls">
      <Loader2 v-if="loading" class="h-5 w-5 animate-spin text-ink-gray-4" />
      <template v-else-if="error">
        <p class="flex items-start gap-1 text-xs text-ink-red">
          <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{{ missingColumn ? 'Column no longer exists — pick another.' : error }}</span>
        </p>
      </template>
      <span v-else class="flex min-w-0 items-baseline gap-2" :class="alignCls">
        <span
          class="truncate text-2xl text-ink-gray-9"
          :class="config.bold ? 'font-bold' : 'font-semibold'"
          :style="[valueColorStyle, config.fontFamily ? { fontFamily: config.fontFamily } : {}, config.valueFontSize ? { fontSize: `${config.valueFontSize}px`, lineHeight: 1 } : {}]"
          :title="display"
        >
          {{ display }}
        </span>
        <span
          v-if="delta"
          class="inline-flex shrink-0 items-center gap-0.5 text-xs font-semibold"
          :class="deltaColorCls"
          :title="deltaTitle"
        >
          <component :is="deltaIcon" class="h-3.5 w-3.5" />
          {{ deltaText }}
        </span>
      </span>
    </div>
    <!-- #14 target line: keep the goal legible even before a numeric value lands. -->
    <p
      v-if="hasTarget"
      class="mt-1 truncate text-[11px] text-ink-gray-5"
      :title="`Target: ${targetDisplay}`"
    >
      Target: {{ targetDisplay }}
    </p>

    <!-- #14 sparkline: the metric's trend over the chosen temporal column. Drawn only when
         enabled (`showSpark`) and the series has points; the shape follows `sparkType`. -->
    <div
      v-if="(config.showSpark !== false) && !error && (sparkPoints || sparkBars)"
      class="mt-2"
      :title="sparkTitle"
    >
      <svg
        v-if="config.sparkType === 'bar'"
        class="h-6 w-full text-primary"
        :style="config.accent ? { color: config.accent } : undefined"
        :viewBox="`0 0 ${SPARK_W} ${SPARK_H}`"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <rect
          v-for="(b, i) in sparkBars"
          :key="i"
          :x="b.x"
          :y="b.y"
          :width="b.w"
          :height="b.h"
          fill="currentColor"
          fill-opacity="0.6"
        />
      </svg>
      <svg
        v-else
        class="h-6 w-full text-primary"
        :style="config.accent ? { color: config.accent } : undefined"
        :viewBox="`0 0 ${SPARK_W} ${SPARK_H}`"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <polygon
          v-if="(config.sparkType ?? 'area') === 'area' && sparkPolygon"
          :points="sparkPolygon ?? undefined"
          fill="currentColor"
          fill-opacity="0.15"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linejoin="round"
          vector-effect="non-scaling-stroke"
        />
        <polyline
          v-else
          :points="sparkPoints ?? undefined"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linejoin="round"
          stroke-linecap="round"
          vector-effect="non-scaling-stroke"
        />
      </svg>
    </div>

    <!-- TASK-037: metric editor lives in the side settings drawer (Power BI–style) when the card
         is selected, so it always opens at full size. Teleported into the drawer body. -->
    <Teleport to="#tile-settings-drawer-body">
    <template v-if="selected">
      <div
        class="js-export-exclude space-y-3 rounded-3 border border-outline-gray-2 bg-surface-base p-3"
      >
        <div class="flex items-center justify-between">
          <p class="px-0.5 text-[11px] font-semibold uppercase tracking-wide text-ink-gray-5">Edit KPI</p>
        </div>
        <div>
          <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Title (optional)</label>
          <input
            type="text"
            :class="selectCls"
            :value="config.title ?? ''"
            :placeholder="autoTitle"
            @input="onTitleChange(($event.target as HTMLInputElement).value)"
          />
        </div>
        <div>
          <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Measure</label>
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
          <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Aggregation</label>
          <select
            :class="selectCls"
            :value="config.aggregation"
            @change="onAggChange(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="a in aggOptions" :key="a" :value="a">{{ AGG_LABEL[a] }}</option>
          </select>
        </div>
        <div>
          <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Target (optional)</label>
          <input
            type="number"
            inputmode="decimal"
            :class="selectCls"
            :value="config.target ?? ''"
            placeholder="No target"
            @input="onTargetChange(($event.target as HTMLInputElement).value)"
          />
        </div>
        <div v-if="hasTarget">
          <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Direction</label>
          <select
            :class="selectCls"
            :value="config.targetMode ?? 'higher_better'"
            @change="onTargetModeChange(($event.target as HTMLSelectElement).value)"
          >
            <option value="higher_better">Higher is better</option>
            <option value="lower_better">Lower is better</option>
          </select>
        </div>
        <div v-if="trendOptions.length > 0">
          <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Trend by</label>
          <select
            :class="selectCls"
            :value="config.trendDimension ?? ''"
            @change="onTrendChange(($event.target as HTMLSelectElement).value)"
          >
            <option value="">None</option>
            <option v-for="c in trendOptions" :key="c.name" :value="c.name">{{ c.name }}</option>
          </select>
        </div>

        <!-- TASK-044: per-KPI formatting + presentation controls. All optional; empty ⇒ default. -->
        <div class="mt-1 border-t border-outline-gray-1 pt-2">
          <p class="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-gray-5">Style</p>
          <div class="grid grid-cols-2 gap-1.5 mb-1.5">
            <div>
              <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Font Family</label>
              <select :class="selectCls" :value="config.fontFamily ?? ''" @change="patch({ fontFamily: (($event.target as HTMLSelectElement).value) || null })">
                <option value="">Default (Inter)</option>
                <option value="Arial, sans-serif">Arial</option>
                <option value="'Times New Roman', serif">Times</option>
                <option value="'Courier New', monospace">Courier</option>
                <option value="'Comic Sans MS', cursive">Comic Sans</option>
              </select>
            </div>
            <div>
              <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Value Size</label>
              <select :class="selectCls" :value="config.valueFontSize ?? ''" @change="patch({ valueFontSize: numOrNull(($event.target as HTMLSelectElement).value) })">
                <option value="">Default (24px)</option>
                <option value="16">16px</option>
                <option value="20">20px</option>
                <option value="24">24px</option>
                <option value="32">32px</option>
                <option value="40">40px</option>
                <option value="48">48px</option>
                <option value="56">56px</option>
                <option value="64">64px</option>
              </select>
            </div>
          </div>
          <div class="mb-1">
            <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Decimals</label>
            <input type="number" min="0" max="8" :class="selectCls" :value="config.decimals ?? ''" placeholder="global" @change="patch({ decimals: numOrNull(($event.target as HTMLInputElement).value) })" />
          </div>
          <div class="mb-1 flex items-center gap-3 text-[12px] text-ink-gray-7">
            <label class="flex items-center gap-1"><input type="checkbox" class="h-4 w-4 accent-primary" :checked="config.thousands ?? true" @change="patch({ thousands: ($event.target as HTMLInputElement).checked })" /> Thousands</label>
            <label class="flex items-center gap-1"><input type="checkbox" class="h-4 w-4 accent-primary" :checked="config.currency === true" @change="patch({ currency: ($event.target as HTMLInputElement).checked })" /> Currency</label>
          </div>
          <div class="mb-1 flex gap-2">
            <div class="flex-1">
              <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Prefix</label>
              <input type="text" :class="selectCls" :value="config.prefix ?? ''" placeholder="e.g. $" @change="patch({ prefix: (($event.target as HTMLInputElement).value).trim() || null })" />
            </div>
            <div class="flex-1">
              <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Suffix</label>
              <input type="text" :class="selectCls" :value="config.suffix ?? ''" placeholder="e.g. %" @change="patch({ suffix: (($event.target as HTMLInputElement).value).trim() || null })" />
            </div>
          </div>
          <label class="mb-1 flex items-center justify-between gap-2 text-[12px] text-ink-gray-7">
            <span>Colour by target</span>
            <input type="checkbox" class="h-4 w-4 accent-primary" :checked="config.colorByTarget === true" @change="patch({ colorByTarget: ($event.target as HTMLInputElement).checked })" />
          </label>
          <label class="mb-1 flex items-center justify-between gap-2 text-[12px] text-ink-gray-7">
            <span>Show sparkline</span>
            <input type="checkbox" class="h-4 w-4 accent-primary" :checked="config.showSpark !== false" @change="patch({ showSpark: ($event.target as HTMLInputElement).checked })" />
          </label>
          <div class="mb-1">
            <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Sparkline type</label>
            <select :class="selectCls" :value="config.sparkType ?? 'area'" @change="patch({ sparkType: (($event.target as HTMLSelectElement).value) as KpiConfig['sparkType'] })">
              <option value="line">Line</option>
              <option value="area">Area</option>
              <option value="bar">Bar</option>
            </select>
          </div>
          <div class="mb-1">
            <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Alignment</label>
            <select :class="selectCls" :value="config.align ?? 'left'" @change="patch({ align: (($event.target as HTMLSelectElement).value) as KpiConfig['align'] })">
              <option value="left">Left</option>
              <option value="center">Center</option>
            </select>
          </div>
          <div class="flex gap-2">
            <div class="flex-1">
              <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Border</label>
              <select :class="selectCls" :value="config.border === false ? 'off' : 'on'" @change="patch({ border: (($event.target as HTMLSelectElement).value) === 'on' })">
                <option value="on">On</option>
                <option value="off">Off</option>
              </select>
            </div>
            <div class="flex-1">
              <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Radius</label>
              <select :class="selectCls" :value="config.radius ?? 'md'" @change="patch({ radius: (($event.target as HTMLSelectElement).value) as KpiConfig['radius'] })">
                <option value="sm">Small</option>
                <option value="md">Medium</option>
                <option value="lg">Large</option>
              </select>
            </div>
            <div class="flex-1">
              <label class="mb-1 block text-[11px] font-medium text-ink-gray-6">Shadow</label>
              <select :class="selectCls" :value="config.shadow ? 'on' : 'off'" @change="patch({ shadow: (($event.target as HTMLSelectElement).value) === 'on' })">
                <option value="off">Off</option>
                <option value="on">On</option>
              </select>
            </div>
          </div>
          <button type="button" class="mt-1 w-full rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-1 text-[11px] text-ink-gray-6 hover:bg-surface-gray-2 hover:text-primary" @click="resetStyle">
            Reset style to default
          </button>
        </div>
      </div>
    </template>
    </Teleport>

    <!-- TASK-033/036 colour popover (ResultsTable menuOpen + fixed-backdrop idiom). Two
         targets — sparkline accent + card background — each with presets, a native any-colour
         picker, a hex field, and a reset. `.no-drag` keeps the floating panel from starting a
         tile drag. Picking does NOT close the panel, so both sections stay usable. -->
    <Teleport to="body">
    <template v-if="colorOpen">
      <div class="js-export-exclude no-drag fixed inset-0 z-40" @click="colorOpen = false"></div>
      <div
        class="js-export-exclude no-drag fixed z-50 w-56 overflow-auto rounded-3 border border-outline-gray-2 bg-surface-base p-2.5 shadow-lg"
        :style="{ top: `${colorPos.y}px`, left: `${colorPos.x}px`, maxHeight: `${colorMaxH}px`, transform: 'translateX(-100%)' }"
      >
        <!-- Sparkline accent -->
        <p class="mb-1.5 px-0.5 text-[11px] font-medium text-ink-gray-6">Sparkline colour</p>
        <div class="grid grid-cols-4 gap-1.5">
          <button
            v-for="c in CHART_PALETTE"
            :key="c"
            type="button"
            class="h-7 w-7 rounded-2 border transition-transform hover:scale-110"
            :class="config.accent === c ? 'border-ink-gray-8 ring-1 ring-ink-gray-8' : 'border-outline-gray-2'"
            :style="{ backgroundColor: c }"
            :title="c"
            @click="pickColor(c)"
          ></button>
        </div>
        <div class="mt-2 flex items-center gap-1.5">
          <input
            type="color"
            class="h-7 w-8 shrink-0 cursor-pointer rounded-2 border border-outline-gray-2 bg-surface-base p-0.5"
            :value="asHexInput(config.accent)"
            title="Custom colour"
            @change="pickColor(($event.target as HTMLInputElement).value)"
          />
          <input
            type="text"
            class="w-full min-w-0 rounded-2 border border-outline-gray-2 bg-surface-base px-1.5 py-1 text-[11px] text-ink-gray-8 focus:border-primary-5 focus:outline-none"
            :value="config.accent ?? ''"
            placeholder="#hex / preset"
            @change="onAccentHex(($event.target as HTMLInputElement).value)"
            @keydown.enter="onAccentHex(($event.target as HTMLInputElement).value)"
          />
          <button
            type="button"
            class="shrink-0 rounded-2 border border-outline-gray-2 px-2 py-1 text-[11px] transition-colors hover:bg-surface-gray-2"
            :class="config.accent ? 'text-ink-gray-7' : 'text-primary'"
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
  </div>
</template>
