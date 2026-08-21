<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import { Loader2 } from '@lucide/vue'
import { useSession } from '../composables/useSession'
import { fetchData, apiErrorMessage } from '../services/api'
import type { DataColumn } from '../types'

// Window size for one fetch: matches the backend's default `limit` and is the
// infinite-scroll page size (the backend clamps anything above 1000).
const PAGE = 500
const ROW_H = 36   // px; fixed row height -> no per-row measurement needed
const COL_W = 160  // px; fixed column width -> header/body columns stay aligned

const { sessionUuid, tableName } = useSession()

const rows = ref<Record<string, unknown>[]>([])
const columns = ref<DataColumn[]>([])
const total = ref(0)
const loading = ref(false)
const gridError = ref<string | null>(null)
const scrollEl = ref<HTMLDivElement | null>(null)

const rowVirtualizer = useVirtualizer<HTMLDivElement, HTMLDivElement>(
  computed(() => ({
    count: rows.value.length,
    getScrollElement: () => scrollEl.value,
    estimateSize: () => ROW_H,
    overscan: 12,
  })),
)
const virtualRows = computed(() => rowVirtualizer.value.getVirtualItems())
const totalSize = computed(() => rowVirtualizer.value.getTotalSize())
const gridWidth = computed(() => columns.value.length * COL_W)

async function loadWindow(offset: number): Promise<void> {
  const uuid = sessionUuid.value
  if (!uuid || loading.value) return
  if (offset > 0 && rows.value.length >= total.value) return // fully loaded
  loading.value = true
  gridError.value = null
  try {
    const res = await fetchData(uuid, {
      offset,
      limit: PAGE,
      tableName: tableName.value ?? undefined,
    })
    // Session may have switched (a new upload) while this fetch was in flight —
    // drop the stale window rather than writing another session's rows.
    if (uuid !== sessionUuid.value) return
    if (offset === 0) {
      columns.value = res.columns
      rows.value = res.rows
    } else {
      rows.value = rows.value.concat(res.rows)
    }
    total.value = res.total
  } catch (e) {
    if (uuid === sessionUuid.value) gridError.value = apiErrorMessage(e)
  } finally {
    if (uuid === sessionUuid.value) loading.value = false
  }
}

// A new (or cleared) session resets the grid and loads the first window.
watch(
  sessionUuid,
  (uuid) => {
    rows.value = []
    columns.value = []
    total.value = 0
    gridError.value = null
    // Release the guard so a switch mid-load isn't blocked by the prior session's
    // in-flight fetch; that stale fetch is discarded by the uuid check in loadWindow.
    loading.value = false
    if (uuid) void loadWindow(0)
  },
  { immediate: true },
)

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
      <h3 class="text-sm font-semibold text-ink-gray-8">Data Grid</h3>
      <span class="text-xs text-ink-gray-5">
        <template v-if="sessionUuid">
          {{ rows.length.toLocaleString() }} / {{ total.toLocaleString() }} rows
          <span v-if="loading" class="inline-flex items-center gap-1 text-primary">
            <Loader2 class="h-3 w-3 animate-spin" /> loading…
          </span>
        </template>
        <template v-else>0 rows</template>
      </span>
    </div>

    <!-- Scroll container is always mounted so the virtualizer can attach to it
         before any data arrives; the states below render inside it. -->
    <div ref="scrollEl" class="overflow-auto relative" style="height: 440px">
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

      <div v-else :style="{ width: gridWidth + 'px', minWidth: '100%' }">
        <!-- Sticky header row (pins vertically; scrolls horizontally with body) -->
        <div class="flex sticky top-0 z-10 border-b border-outline-gray-1 bg-surface-gray-1">
          <div
            v-for="col in columns"
            :key="col.name"
            class="shrink-0 truncate px-3 py-2 text-xs font-semibold text-ink-gray-7"
            :style="{ width: COL_W + 'px' }"
            :title="col.name + ' · ' + col.type"
          >
            {{ col.name }}
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
              v-for="col in columns"
              :key="col.name"
              class="shrink-0 truncate px-3 py-2 text-xs text-ink-gray-8"
              :style="{ width: COL_W + 'px' }"
              :title="cell(rows[vRow.index], col.name)"
            >
              {{ cell(rows[vRow.index], col.name) }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
