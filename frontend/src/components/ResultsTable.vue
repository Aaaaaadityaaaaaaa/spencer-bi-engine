<script setup lang="ts">
// Presentational, read-only results table for one /execute result. It holds NO
// fetch state -- the parent (QueryConsole) owns the request and passes the whole
// {columns, rows, truncated} in as props. This is a one-shot sandboxed result capped
// server-side at MAX_ROWS, so a simple sticky-header scroll table is the right model
// (NOT the TASK-006 fetch-windowed virtualizer, which pages an unbounded table).
import { ref } from 'vue'
import { Download, ChevronDown, Check, Loader2 } from '@lucide/vue'
import type { DataColumn } from '../types'
import {
  toCsv,
  toJson,
  toTsv,
  downloadCsv,
  downloadText,
  downloadBlob,
  copyToClipboard,
} from '../utils/csvExport'
import { exportRows, blobErrorMessage } from '../services/api'

const props = defineProps<{
  columns: DataColumn[]
  rows: Record<string, unknown>[]
  truncated: boolean
  // Needed only for the server-side Excel export; CSV/JSON/clipboard work without it.
  sessionUuid: string | null
}>()

// Export the exact rows in hand. If the result was truncated at the server cap, only
// those capped rows are written -- the footer already says so. CSV/JSON and clipboard
// are built client-side from the rows already here; Excel (.xlsx) is the one format with
// no browser encoder, so it round-trips to the server (POST /export/rows).
const menuOpen = ref(false)
const menuPos = ref<{ x: number; y: number }>({ x: 0, y: 0 })
const busy = ref(false)
const copied = ref(false)
const exportError = ref<string | null>(null)

function toggleMenu(e: MouseEvent): void {
  if (menuOpen.value) {
    menuOpen.value = false
    return
  }
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  menuPos.value = { x: r.right, y: r.bottom }
  menuOpen.value = true
}

function doCsv(): void {
  menuOpen.value = false
  downloadCsv('query-result.csv', toCsv(props.columns, props.rows))
}

function doJson(): void {
  menuOpen.value = false
  downloadText('query-result.json', toJson(props.columns, props.rows))
}

async function doCopy(): Promise<void> {
  menuOpen.value = false
  const ok = await copyToClipboard(toTsv(props.columns, props.rows))
  if (ok) {
    copied.value = true
    window.setTimeout(() => (copied.value = false), 1500)
  } else {
    exportError.value = 'Clipboard access was blocked by the browser'
  }
}

async function doExcel(): Promise<void> {
  menuOpen.value = false
  const uuid = props.sessionUuid
  if (!uuid || busy.value || props.rows.length === 0) return
  busy.value = true
  exportError.value = null
  try {
    const blob = await exportRows(uuid, props.columns.map((c) => c.name), props.rows)
    downloadBlob('query-result.xlsx', blob)
  } catch (e) {
    // A failed blob request carries its error body as a Blob, not parsed JSON.
    exportError.value = await blobErrorMessage(e)
  } finally {
    busy.value = false
  }
}

// Same display coercion as DataGrid: NULL/undefined -> blank; objects -> JSON.
function cell(row: Record<string, unknown>, name: string): string {
  const v = row[name]
  if (v === null || v === undefined) return ''
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}
</script>

<template>
  <div class="overflow-hidden rounded-4 border border-outline-gray-1 bg-surface-base">
    <div class="flex items-center justify-between border-b border-outline-gray-1 bg-surface-gray-1 px-3 py-1.5">
      <span class="text-[11px] text-ink-gray-5">{{ rows.length.toLocaleString() }} rows</span>
      <button
        type="button"
        class="inline-flex items-center gap-1 rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-1 text-[11px] font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2 disabled:cursor-not-allowed disabled:opacity-50"
        :class="{ 'bg-surface-gray-2': menuOpen }"
        :disabled="rows.length === 0 || busy"
        title="Export these results"
        @click.stop="toggleMenu($event)"
      >
        <Check v-if="copied" class="h-3.5 w-3.5 text-primary" />
        <Loader2 v-else-if="busy" class="h-3.5 w-3.5 animate-spin text-primary" />
        <Download v-else class="h-3.5 w-3.5" />
        {{ copied ? 'Copied' : 'Export' }}
        <ChevronDown class="h-3 w-3" />
      </button>
    </div>
    <div class="max-h-[360px] overflow-auto">
      <table class="w-full border-collapse text-xs">
        <thead class="sticky top-0 z-10 bg-surface-gray-1">
          <tr>
            <th
              v-for="col in columns"
              :key="col.name"
              class="whitespace-nowrap border-b border-outline-gray-1 px-3 py-2 text-left font-semibold text-ink-gray-7"
              :title="col.name + ' · ' + col.type"
            >
              {{ col.name }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="rows.length === 0">
            <td
              :colspan="columns.length || 1"
              class="px-3 py-6 text-center text-ink-gray-4"
            >
              Query returned no rows.
            </td>
          </tr>
          <tr
            v-for="(row, i) in rows"
            :key="i"
            class="hover:bg-surface-gray-1"
          >
            <td
              v-for="col in columns"
              :key="col.name"
              class="max-w-[280px] truncate border-b border-outline-gray-1 px-3 py-1.5 text-ink-gray-8"
              :title="cell(row, col.name)"
            >
              {{ cell(row, col.name) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div
      v-if="truncated"
      class="border-t border-outline-gray-1 bg-surface-gray-1 px-3 py-1.5 text-[11px] text-ink-gray-5"
    >
      Showing the first {{ rows.length.toLocaleString() }} rows — result truncated at the server cap.
    </div>

    <div
      v-if="exportError"
      class="border-t border-outline-gray-1 bg-surface-gray-1 px-3 py-1.5 text-[11px] text-ink-red"
    >
      {{ exportError }}
    </div>

    <!-- Export menu (fixed-positioned + backdrop so the container's overflow-hidden
         can't clip it). CSV/JSON/clipboard are built client-side from the rows in hand;
         Excel round-trips to the server (no browser .xlsx encoder). -->
    <div v-if="menuOpen" class="fixed inset-0 z-40" @click="menuOpen = false"></div>
    <div
      v-if="menuOpen"
      class="fixed z-50 w-48 overflow-hidden rounded-3 border border-outline-gray-1 bg-surface-base py-1 shadow-md"
      :style="{ top: menuPos.y + 4 + 'px', left: menuPos.x + 'px', transform: 'translateX(-100%)' }"
    >
      <button type="button" class="flex w-full items-center px-3 py-1.5 text-left text-xs text-ink-gray-8 transition-colors hover:bg-surface-gray-2" @click="doCsv">
        CSV (.csv)
      </button>
      <button type="button" class="flex w-full items-center px-3 py-1.5 text-left text-xs text-ink-gray-8 transition-colors hover:bg-surface-gray-2" @click="doJson">
        JSON (.json)
      </button>
      <button
        type="button"
        class="flex w-full items-center px-3 py-1.5 text-left text-xs text-ink-gray-8 transition-colors hover:bg-surface-gray-2 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="!sessionUuid"
        title="Encoded server-side as a real .xlsx"
        @click="doExcel"
      >
        Excel (.xlsx)
      </button>
      <div class="my-1 border-t border-outline-gray-1"></div>
      <button type="button" class="flex w-full items-center px-3 py-1.5 text-left text-xs text-ink-gray-8 transition-colors hover:bg-surface-gray-2" @click="doCopy">
        Copy to clipboard
      </button>
    </div>
  </div>
</template>
