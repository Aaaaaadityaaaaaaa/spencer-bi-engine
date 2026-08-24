<script setup lang="ts">
// One KPI card. Presentation + its own inline editor; it does NOT fetch. ChartCanvas
// owns all data orchestration and passes the result down, so every tile's loading /
// error state is handled uniformly in one place.
import { computed, ref } from 'vue'
import { AlertCircle, Loader2, Pencil, X } from '@lucide/vue'
import type { Aggregation, AggregateValue, ColumnMeta, KpiConfig } from '../types'
import { AGG_LABEL, allowedAggregations, coerceAggregation } from '../utils/aggregations'

const props = defineProps<{
  config: KpiConfig
  columns: ColumnMeta[]
  loading: boolean
  error: string | null
  value: AggregateValue
}>()

const emit = defineEmits<{
  'update:config': [config: KpiConfig]
  remove: [id: number]
}>()

const editing = ref(false)

const title = computed(() =>
  props.config.measure === null
    ? 'Total rows'
    : `${AGG_LABEL[props.config.aggregation]} of ${props.config.measure}`,
)

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

const selectCls =
  'w-full rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-1 text-xs text-ink-gray-8 focus:border-primary-5 focus:outline-none'
</script>

<template>
  <div class="group relative flex flex-col rounded-5 border border-outline-gray-1 bg-surface-base p-4 shadow-sm">
    <!-- Label + hover actions -->
    <div class="flex items-start justify-between gap-2">
      <span class="truncate text-xs font-medium uppercase tracking-wide text-ink-gray-5" :title="title">
        {{ title }}
      </span>
      <div class="flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <button
          type="button"
          class="rounded-2 p-1 text-ink-gray-4 hover:bg-surface-gray-2 hover:text-ink-gray-7"
          :title="editing ? 'Done' : 'Edit metric'"
          @click="editing = !editing"
        >
          <Pencil class="h-3 w-3" />
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

    <!-- Value -->
    <div class="mt-2 flex min-h-[2.25rem] items-center">
      <Loader2 v-if="loading" class="h-5 w-5 animate-spin text-ink-gray-4" />
      <template v-else-if="error">
        <p class="flex items-start gap-1 text-xs text-ink-red">
          <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{{ missingColumn ? 'Column no longer exists — pick another.' : error }}</span>
        </p>
      </template>
      <span v-else class="truncate text-2xl font-semibold text-ink-gray-9" :title="display">
        {{ display }}
      </span>
    </div>

    <!-- Inline editor -->
    <div v-if="editing" class="mt-3 space-y-2 border-t border-outline-gray-1 pt-3">
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
    </div>
  </div>
</template>
