<script setup lang="ts">
// Table export menu (Wave 2 / #10): downloads the whole active session table in any
// format the backend supports (csv/tsv/json/parquet/xlsx). The backend resolves + scopes
// the table and streams bytes; this component only triggers the browser download. Reused
// by TableView; reads the useSession singleton so it always targets the active table.
import { ref } from 'vue'
import { Download, ChevronDown } from '@lucide/vue'
import { useSession } from '../composables/useSession'
import { exportTable, apiErrorMessage } from '../services/api'
import type { ExportFormat } from '../services/api'

const { sessionUuid, tableName } = useSession()
const open = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)

// Mirrors backend export_service.TABLE_FORMATS.
const formats: ExportFormat[] = ['csv', 'tsv', 'json', 'parquet', 'xlsx']

async function doExport(fmt: ExportFormat): Promise<void> {
  if (!sessionUuid.value || busy.value) return
  busy.value = true
  error.value = null
  open.value = false
  try {
    const blob = await exportTable(sessionUuid.value, fmt, tableName.value ?? undefined)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `spencer-export.${fmt}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch (e) {
    error.value = apiErrorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="relative inline-block">
    <button
      type="button"
      :disabled="busy"
      class="btn btn-ghost"
      :title="busy ? 'Exporting…' : 'Export table'"
      @click="open = !open"
    >
      <Download class="h-4 w-4" />
      Export
      <ChevronDown class="h-3.5 w-3.5" />
    </button>

    <div
      v-if="open"
      class="absolute right-0 z-20 mt-1 w-32 rounded-3 border border-outline-gray-1 bg-surface-base py-1 shadow-md"
      @mouseleave="open = false"
    >
      <button
        v-for="f in formats"
        :key="f"
        type="button"
        class="block w-full px-3 py-1.5 text-left text-sm text-ink-gray-7 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-9"
        @click="doExport(f)"
      >
        {{ f.toUpperCase() }}
      </button>
    </div>

    <p v-if="error" class="absolute right-0 mt-1 w-56 rounded-3 border border-ink-red/30 bg-surface-base px-2 py-1 text-xs text-ink-red">
      {{ error }}
    </p>
  </div>
</template>
