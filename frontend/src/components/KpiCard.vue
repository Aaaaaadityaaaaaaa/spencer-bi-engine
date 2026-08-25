<script setup lang="ts">
// One KPI card. Presentation + its own inline editor; it does NOT fetch. ChartCanvas
// owns all data orchestration and passes the result down, so every tile's loading /
// error state is handled uniformly in one place.
import { computed, ref } from 'vue'
import {
  AlertCircle,
  Bold,
  GripVertical,
  Loader2,
  Minus,
  Palette,
  Pencil,
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

const props = defineProps<{
  config: KpiConfig
  columns: ColumnMeta[]
  loading: boolean
  error: string | null
  value: AggregateValue
  // TASK-031: the metric-over-time series for the sparkline (ChartCanvas fetches it,
  // exactly like `value`). Null when this card has no trend dimension or none loaded yet.
  trend?: AggregateResponse | null
}>()

const emit = defineEmits<{
  'update:config': [config: KpiConfig]
  remove: [id: number]
}>()

const editing = ref(false)

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

const display = computed(() => {
  const v = props.value
  if (v === null) return '—'
  if (typeof v === 'string') return v // MIN/MAX over a date arrives as an ISO string
  if (!Number.isFinite(v)) return '—'
  const frac = props.config.aggregation === 'avg' || !Number.isInteger(v) ? 2 : 0
  return v.toLocaleString(undefined, { maximumFractionDigits: frac })
})

// --- #14 delta vs target ----------------------------------------------------------
function fmtNum(n: number): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: Number.isInteger(n) ? 0 : 2 })
}

const hasTarget = computed(() => props.config.target !== null && props.config.target !== undefined)

// The value as a finite number, or null. MIN/MAX over a date is an ISO string, and
// loading/error/empty is null — none of those can be compared to a numeric target.
const numericValue = computed<number | null>(() => {
  const v = props.value
  return typeof v === 'number' && Number.isFinite(v) ? v : null
})

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
function toggleColor(e: MouseEvent): void {
  if (colorOpen.value) {
    colorOpen.value = false
    return
  }
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  colorPos.value = { x: r.right, y: r.bottom }
  editing.value = false // one floating panel open at a time
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

// TASK-037: the metric editor is a FLOATING popover, not an in-card block. On a small tile an
// in-flow editor was clipped by the card's fixed height + `overflow-hidden`, so you had to
// enlarge the card before you could edit it. Anchored to the pencil and clamped to the
// viewport, it now opens at full size regardless of how small (or where) the card is.
const editorPos = ref<{ x: number; y: number }>({ x: 0, y: 0 })
function toggleEditor(e: MouseEvent): void {
  if (editing.value) {
    editing.value = false
    return
  }
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  const M = 8 // viewport margin; PW/PH ≈ the panel's design box (w-64, up to ~6 fields)
  const PW = 256
  const PH = 340
  let x = r.left
  if (x + PW > window.innerWidth - M) x = window.innerWidth - M - PW
  if (x < M) x = M
  let y = r.bottom + 4
  if (y + PH > window.innerHeight - M) y = Math.max(M, window.innerHeight - M - PH)
  editorPos.value = { x, y }
  colorOpen.value = false // one floating panel open at a time
  editing.value = true
}

function toggleClean(): void {
  emit('update:config', { ...props.config, hideControls: !props.config.hideControls })
}

const selectCls =
  'w-full rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-1 text-xs text-ink-gray-8 focus:border-primary-5 focus:outline-none'
</script>

<template>
  <div
    class="tile-drag-handle group relative flex h-full flex-col overflow-hidden rounded-5 border border-outline-gray-1 bg-surface-base p-4 shadow-sm"
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
      <div class="js-export-exclude flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <!-- Edit metric (a control) — hidden by the clean toggle; present/export hide the
             whole group via js-export-exclude, leaving just label + value + spark. -->
        <button
          v-if="!config.hideControls"
          type="button"
          class="rounded-2 p-1 hover:bg-surface-gray-2"
          :class="editing ? 'text-primary' : 'text-ink-gray-4 hover:text-ink-gray-7'"
          :title="editing ? 'Close editor' : 'Edit metric'"
          @click="toggleEditor"
        >
          <Pencil class="h-3 w-3" />
        </button>
        <!-- Presentation toolbar (always available so a cleaned card can be recoloured /
             restored / removed). -->
        <button
          type="button"
          class="rounded-2 p-1 hover:bg-surface-gray-2"
          :class="config.accent || config.bg ? 'text-primary' : 'text-ink-gray-4 hover:text-primary'"
          title="Colour & card background"
          @click="toggleColor"
        >
          <Palette class="h-3 w-3" />
        </button>
        <button
          type="button"
          class="rounded-2 p-1 hover:bg-surface-gray-2"
          :class="config.bold ? 'text-primary' : 'text-ink-gray-4 hover:text-primary'"
          :title="config.bold ? 'Unbold title & value' : 'Bold title & value'"
          @click="toggleBold"
        >
          <Bold class="h-3 w-3" />
        </button>
        <button
          type="button"
          class="rounded-2 p-1 hover:bg-surface-gray-2"
          :class="config.hideControls ? 'text-primary' : 'text-ink-gray-4 hover:text-primary'"
          :title="config.hideControls ? 'Show controls' : 'Hide controls (keep title + value)'"
          @click="toggleClean"
        >
          <SlidersHorizontal class="h-3 w-3" />
        </button>
        <button
          type="button"
          class="rounded-2 p-1 text-ink-gray-4 hover:bg-surface-gray-2 hover:text-ink-red"
          title="Remove card"
          @click="emit('remove', config.id)"
        >
          <X class="h-3 w-3" />
        </button>
      </div>
    </div>

    <!-- Value + #14 delta-vs-target chip -->
    <div class="mt-2 flex min-h-[2.25rem] items-center">
      <Loader2 v-if="loading" class="h-5 w-5 animate-spin text-ink-gray-4" />
      <template v-else-if="error">
        <p class="flex items-start gap-1 text-xs text-ink-red">
          <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{{ missingColumn ? 'Column no longer exists — pick another.' : error }}</span>
        </p>
      </template>
      <span v-else class="flex min-w-0 items-baseline gap-2">
        <span
          class="truncate text-2xl text-ink-gray-9"
          :class="config.bold ? 'font-bold' : 'font-semibold'"
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

    <!-- #14 sparkline: the metric's trend over the chosen temporal column. Drawn only
         when the series has >=2 numeric points and the card isn't in an error state. -->
    <div v-if="!error && sparkPoints" class="mt-2" :title="sparkTitle">
      <svg
        class="h-6 w-full text-primary"
        :style="config.accent ? { color: config.accent } : undefined"
        :viewBox="`0 0 ${SPARK_W} ${SPARK_H}`"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <polyline
          :points="sparkPoints"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linejoin="round"
          stroke-linecap="round"
          vector-effect="non-scaling-stroke"
        />
      </svg>
    </div>

    <!-- TASK-037: metric editor as a FLOATING popover (fixed panel + click-outside backdrop),
         so it opens at full size even when the card is tiny — an in-flow editor was clipped by
         the card's fixed height + `overflow-hidden`, forcing you to enlarge the card first.
         Teleported to <body> so `position: fixed` resolves against the viewport: the grid item's
         CSS transform would otherwise make a fixed child resolve against (and clip to) the item. -->
    <Teleport to="body">
    <template v-if="editing && !config.hideControls">
      <div class="js-export-exclude no-drag fixed inset-0 z-40" @click="editing = false"></div>
      <div
        class="js-export-exclude no-drag fixed z-50 max-h-[70vh] w-64 space-y-2 overflow-auto rounded-3 border border-outline-gray-2 bg-surface-base p-3 shadow-lg"
        :style="{ top: `${editorPos.y}px`, left: `${editorPos.x}px` }"
      >
        <div class="flex items-center justify-between">
          <p class="px-0.5 text-[11px] font-semibold uppercase tracking-wide text-ink-gray-5">Edit KPI</p>
          <button
            type="button"
            class="rounded-2 p-0.5 text-ink-gray-4 hover:bg-surface-gray-2 hover:text-ink-gray-7"
            title="Close"
            @click="editing = false"
          >
            <X class="h-3 w-3" />
          </button>
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
        class="js-export-exclude no-drag fixed z-50 max-h-[70vh] w-56 overflow-auto rounded-3 border border-outline-gray-2 bg-surface-base p-2.5 shadow-lg"
        :style="{ top: `${colorPos.y + 4}px`, left: `${colorPos.x}px`, transform: 'translateX(-100%)' }"
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
