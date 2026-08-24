<script setup lang="ts">
// Read-only column profiler drawer (TASK-015). Opened from the grid's per-column ⋮
// "Profile column" entry; slides in from the right. Every number is computed
// server-side over the WHOLE table (GET /profile/column) -- this component only
// renders the result, and imports NO charting library (the Table bundle stays
// ECharts-free; the histogram + bars are plain CSS).
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { X, Loader2, AlertCircle } from '@lucide/vue'
import { useSession } from '../composables/useSession'
import { fetchColumnProfile, apiErrorMessage } from '../services/api'
import type { ColumnProfile } from '../types'

const props = defineProps<{ column: string | null }>()
const emit = defineEmits<{ close: [] }>()

// sessionUuid/tableName identify the target; dataVersion bumps on every transform/
// undo/redo, so an open panel re-profiles against the new data (or surfaces an
// honest 400 if the profiled column was dropped).
const { sessionUuid, tableName, dataVersion } = useSession()

const profile = ref<ColumnProfile | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

// Monotonic guard: only the newest request may write state. A fast reopen on a
// different column (or a dataVersion bump mid-flight) can't be overwritten by an
// older in-flight response landing late.
let seq = 0
async function load(): Promise<void> {
  const uuid = sessionUuid.value
  const col = props.column
  if (!uuid || !col) return
  const s = ++seq
  loading.value = true
  error.value = null
  try {
    const res = await fetchColumnProfile(uuid, col, tableName.value ?? undefined)
    if (s !== seq) return
    profile.value = res
  } catch (e) {
    if (s !== seq) return
    profile.value = null
    error.value = apiErrorMessage(e)
  } finally {
    if (s === seq) loading.value = false
  }
}

watch(
  () => props.column,
  (col) => {
    if (col) {
      profile.value = null
      error.value = null
      void load()
    } else {
      // Closing: drop stale content and invalidate any in-flight response.
      profile.value = null
      error.value = null
      seq++
    }
  },
  { immediate: true },
)
// Re-profile after a transform while the panel is open (schema/rows changed).
watch(dataVersion, () => {
  if (props.column) void load()
})

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape' && props.column) emit('close')
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

// --- display helpers --------------------------------------------------------
function fmtInt(n: number): string {
  return n.toLocaleString()
}
// mean/median/std: numbers or null.
function fmtNum(v: number | null): string {
  if (v === null || v === undefined) return '—'
  return v.toLocaleString(undefined, { maximumFractionDigits: 3 })
}
// min/max: a number (numeric col) or an ISO string (date col) or null.
function fmtMinMax(v: number | string | null): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') return v.toLocaleString(undefined, { maximumFractionDigits: 3 })
  return v
}
// A top-value label: distinguish an empty string from a blank cell; booleans -> text.
function fmtVal(v: string | number | boolean | null): string {
  if (v === null) return 'null'
  if (v === '') return '(empty)'
  return String(v)
}

const fillPct = computed(() => {
  const p = profile.value
  if (!p || p.total === 0) return 0
  return (p.non_null / p.total) * 100
})
// Bar scaling: divide by the largest count so the tallest bar fills the track.
const histMax = computed(() =>
  profile.value ? Math.max(1, ...profile.value.histogram.map((b) => b.count)) : 1,
)
const topMax = computed(() =>
  profile.value ? Math.max(1, ...profile.value.top_values.map((t) => t.count)) : 1,
)

// Histogram axis labels, index-safe (the array is empty for non-numeric / all-null).
const histLo = computed<number | null>(() => profile.value?.histogram[0]?.x0 ?? null)
const histHi = computed<number | null>(() => {
  const h = profile.value?.histogram
  return h && h.length ? (h[h.length - 1]?.x1 ?? null) : null
})

// A short numeric stat grid, built only for numeric columns.
const numericStats = computed(() => {
  const p = profile.value
  if (!p || p.kind !== 'numeric') return []
  return [
    { label: 'Min', value: fmtMinMax(p.min) },
    { label: 'Max', value: fmtMinMax(p.max) },
    { label: 'Mean', value: fmtNum(p.mean) },
    { label: 'Median', value: fmtNum(p.median) },
    { label: 'Std dev', value: fmtNum(p.std) },
  ]
})
</script>

<template>
  <!-- Backdrop: click-to-close, light dim so the grid stays visible behind it. -->
  <div v-if="column" class="fixed inset-0 z-40 bg-black/20" @click="emit('close')"></div>

  <aside
    v-if="column"
    class="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-outline-gray-1 bg-surface-base shadow-lg"
  >
    <!-- Header -->
    <div class="flex items-start justify-between gap-3 border-b border-outline-gray-1 px-4 py-3">
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <h3 class="truncate text-sm font-semibold text-ink-gray-8" :title="column">{{ column }}</h3>
          <span
            v-if="profile"
            class="shrink-0 rounded-2 bg-surface-gray-2 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-ink-gray-6"
          >
            {{ profile.kind }}
          </span>
        </div>
        <p v-if="profile" class="mt-0.5 truncate text-xs text-ink-gray-4">{{ profile.type }}</p>
      </div>
      <button
        type="button"
        class="shrink-0 rounded-2 p-1 text-ink-gray-4 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-7"
        title="Close (Esc)"
        @click="emit('close')"
      >
        <X class="h-4 w-4" />
      </button>
    </div>

    <!-- Body -->
    <div class="flex-1 overflow-auto p-4">
      <!-- Loading -->
      <div v-if="loading" class="flex items-center justify-center gap-2 py-12 text-sm text-ink-gray-4">
        <Loader2 class="h-4 w-4 animate-spin" /> Profiling…
      </div>

      <!-- Error (e.g. column dropped by a transform -> 400) -->
      <div
        v-else-if="error"
        class="flex items-start gap-2 rounded-3 border border-outline-gray-2 bg-surface-gray-1 p-3 text-sm text-ink-red"
      >
        <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
        <span>{{ error }}</span>
      </div>

      <!-- Profile -->
      <div v-else-if="profile" class="space-y-5">
        <!-- Completeness overview -->
        <section class="space-y-2">
          <div class="grid grid-cols-2 gap-2">
            <div class="rounded-3 border border-outline-gray-1 bg-surface-gray-1 px-3 py-2">
              <div class="text-[11px] uppercase tracking-wide text-ink-gray-4">Rows</div>
              <div class="text-sm font-semibold text-ink-gray-8">{{ fmtInt(profile.total) }}</div>
            </div>
            <div class="rounded-3 border border-outline-gray-1 bg-surface-gray-1 px-3 py-2">
              <div class="text-[11px] uppercase tracking-wide text-ink-gray-4">Distinct</div>
              <div class="text-sm font-semibold text-ink-gray-8">{{ fmtInt(profile.distinct) }}</div>
            </div>
            <div class="rounded-3 border border-outline-gray-1 bg-surface-gray-1 px-3 py-2">
              <div class="text-[11px] uppercase tracking-wide text-ink-gray-4">Filled</div>
              <div class="text-sm font-semibold text-ink-gray-8">{{ fmtInt(profile.non_null) }}</div>
            </div>
            <div class="rounded-3 border border-outline-gray-1 bg-surface-gray-1 px-3 py-2">
              <div class="text-[11px] uppercase tracking-wide text-ink-gray-4">Missing</div>
              <div class="text-sm font-semibold" :class="profile.null_count > 0 ? 'text-ink-red' : 'text-ink-gray-8'">
                {{ fmtInt(profile.null_count) }}
                <span class="text-xs font-normal text-ink-gray-4">({{ profile.null_pct }}%)</span>
              </div>
            </div>
          </div>
          <!-- Completeness bar: filled vs missing -->
          <div class="h-2 w-full overflow-hidden rounded-full bg-surface-gray-3">
            <div class="h-full rounded-full bg-primary" :style="{ width: fillPct + '%' }"></div>
          </div>
          <div class="flex justify-between text-[11px] text-ink-gray-4">
            <span>{{ (100 - profile.null_pct).toFixed(profile.null_pct ? 2 : 0) }}% complete</span>
            <span v-if="profile.null_count > 0">{{ profile.null_pct }}% null</span>
          </div>
        </section>

        <!-- Numeric: stat grid + histogram -->
        <template v-if="profile.kind === 'numeric'">
          <section class="grid grid-cols-2 gap-x-4 gap-y-1.5">
            <div
              v-for="s in numericStats"
              :key="s.label"
              class="flex items-baseline justify-between border-b border-outline-gray-1 py-1"
            >
              <span class="text-xs text-ink-gray-5">{{ s.label }}</span>
              <span class="text-xs font-medium text-ink-gray-8">{{ s.value }}</span>
            </div>
          </section>

          <section v-if="profile.histogram.length" class="space-y-1.5">
            <div class="text-[11px] font-medium uppercase tracking-wide text-ink-gray-4">Distribution</div>
            <div class="flex h-28 items-end gap-0.5">
              <div
                v-for="(bin, i) in profile.histogram"
                :key="i"
                class="flex-1 rounded-t-sm bg-primary/80 transition-colors hover:bg-primary"
                :style="{ height: Math.max(bin.count > 0 ? 3 : 0, (bin.count / histMax) * 100) + '%' }"
                :title="`[${fmtMinMax(bin.x0)}, ${fmtMinMax(bin.x1)}${i === profile.histogram.length - 1 ? ']' : ')'}: ${bin.count}`"
              ></div>
            </div>
            <div class="flex justify-between text-[10px] text-ink-gray-4">
              <span>{{ fmtMinMax(histLo) }}</span>
              <span>{{ fmtMinMax(histHi) }}</span>
            </div>
          </section>
        </template>

        <!-- Temporal: min/max range -->
        <section v-if="profile.kind === 'temporal'" class="grid grid-cols-2 gap-2">
          <div class="rounded-3 border border-outline-gray-1 bg-surface-gray-1 px-3 py-2">
            <div class="text-[11px] uppercase tracking-wide text-ink-gray-4">Earliest</div>
            <div class="truncate text-sm font-medium text-ink-gray-8" :title="fmtMinMax(profile.min)">
              {{ fmtMinMax(profile.min) }}
            </div>
          </div>
          <div class="rounded-3 border border-outline-gray-1 bg-surface-gray-1 px-3 py-2">
            <div class="text-[11px] uppercase tracking-wide text-ink-gray-4">Latest</div>
            <div class="truncate text-sm font-medium text-ink-gray-8" :title="fmtMinMax(profile.max)">
              {{ fmtMinMax(profile.max) }}
            </div>
          </div>
        </section>

        <!-- Top values (categorical / temporal / boolean) -->
        <section v-if="profile.top_values.length" class="space-y-1.5">
          <div class="text-[11px] font-medium uppercase tracking-wide text-ink-gray-4">
            Top values
            <span class="normal-case text-ink-gray-4">(of {{ fmtInt(profile.distinct) }} distinct)</span>
          </div>
          <div
            v-for="(tv, i) in profile.top_values"
            :key="i"
            class="space-y-0.5"
          >
            <div class="flex items-baseline justify-between gap-2 text-xs">
              <span class="truncate text-ink-gray-8" :title="fmtVal(tv.value)">{{ fmtVal(tv.value) }}</span>
              <span class="shrink-0 tabular-nums text-ink-gray-5">{{ fmtInt(tv.count) }}</span>
            </div>
            <div class="h-1.5 w-full overflow-hidden rounded-full bg-surface-gray-2">
              <div class="h-full rounded-full bg-primary/70" :style="{ width: (tv.count / topMax) * 100 + '%' }"></div>
            </div>
          </div>
        </section>

        <!-- All-null / empty fallthrough: nothing kind-specific to show -->
        <p
          v-if="profile.non_null === 0"
          class="rounded-3 border border-outline-gray-1 bg-surface-gray-1 p-3 text-xs text-ink-gray-5"
        >
          This column is entirely empty — every value is null.
        </p>

        <!-- Transparency: the compiled DuckDB SQL behind these numbers -->
        <details class="rounded-3 border border-outline-gray-1 bg-surface-gray-1">
          <summary class="cursor-pointer px-3 py-2 text-xs font-medium text-ink-gray-6">Compiled SQL</summary>
          <pre class="overflow-auto border-t border-outline-gray-1 px-3 py-2 text-[11px] leading-relaxed text-ink-gray-7">{{ profile.compiled_sql }}</pre>
        </details>
      </div>
    </div>
  </aside>
</template>
