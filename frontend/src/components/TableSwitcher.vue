<script setup lang="ts">
// Multi-table switcher (TASK-039 / #32): lists every table in the active session and
// lets the user point the whole app (grid, data-prep, Canvas field lists, Query schema)
// at a different already-loaded table via setActiveTable(), plus add a new secondary
// table with addTable(). Lives in App.vue so it is reachable from every tab; it only
// renders once a session has at least one table. Styling matches the App shell.
import { ref, watch, onMounted } from 'vue'
import { Plus, Database, X, Star, Palette } from '@lucide/vue'
import { useSession } from '../composables/useSession'
import { useAuth } from '../composables/useAuth'
import { displayTableName } from '../utils/tableName'

const { tables, tableName, sessionUuid, uploading, addTable, removeTable, makePrimary, setActiveTable } = useSession()
const { user } = useAuth()
const fileInput = ref<HTMLInputElement | null>(null)

// Global Theme Color state
const appThemeColor = ref('#83bfc8')

onMounted(() => {
  if (user.value?.email) {
    const saved = localStorage.getItem(`spencer_theme_${user.value.email}`)
    if (saved) {
      appThemeColor.value = saved
      document.documentElement.style.setProperty('--primary-5', saved)
    }
  }
})

watch(appThemeColor, (newColor) => {
  document.documentElement.style.setProperty('--primary-5', newColor)
  if (user.value?.email) {
    localStorage.setItem(`spencer_theme_${user.value.email}`, newColor)
  }
})

// Show the original upload name, not the long t_<uuid>_ physical name (backend still
// resolves it on query). The tooltip keeps the real physical name for reference.
function label(t: { table_name: string }): string {
  return displayTableName(t.table_name, sessionUuid.value)
}

// Hidden file input is triggered by the "Add table" button; the chosen file is handed
// straight to addTable() (which uploads + registers it as a secondary table). Resetting
// the input value lets the same file be re-picked after a failed upload.
function triggerAdd(): void {
  fileInput.value?.click()
}
function onFile(e: Event): void {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) void addTable(file)
  input.value = ''
}
</script>

<template>
  <div
    v-if="tables.length"
    class="flex shrink-0 items-center justify-between overflow-x-auto border-b border-outline-gray-1 bg-surface-gray-2/50 px-6 py-3"
  >
    <div class="flex items-center gap-4">
      <div class="flex items-center gap-1.5 rounded-full bg-white px-3 py-1 shadow-sm ring-1 ring-outline-gray-2/60">
        <Database class="h-3.5 w-3.5 text-primary-5" />
        <span class="text-xs font-semibold uppercase tracking-wider text-ink-gray-5">Datasets</span>
      </div>
      
      <!-- Pill style segmented control -->
      <div class="flex items-center gap-1 rounded-3 bg-outline-gray-2/30 p-1">
        <div
          v-for="t in tables"
          :key="t.table_name"
          class="group relative flex shrink-0 items-center rounded-2 transition-all duration-300"
          :class="t.table_name === tableName ? 'bg-white shadow-sm ring-1 ring-outline-gray-2/50 text-primary-7' : 'text-ink-gray-6 hover:bg-white/50 hover:text-ink-gray-8'"
        >
          <button
            type="button"
            class="px-3 py-1 text-sm font-medium transition-colors"
            :title="t.table_name"
            @click="setActiveTable(t.table_name)"
          >
            {{ label(t) }}
            <span v-if="t.is_primary" class="ml-1.5 inline-flex items-center justify-center rounded bg-primary-1 px-1.5 py-0.5 text-[9px] font-bold uppercase text-primary-7">primary</span>
          </button>
          
          <div class="flex items-center opacity-0 group-hover:opacity-100 transition-opacity duration-200 pr-1">
            <button
              v-if="!t.is_primary"
              type="button"
              class="p-1 text-ink-gray-4 hover:text-amber-500 transition-colors"
              title="Make primary"
              @click.stop="makePrimary(t.table_name)"
            >
              <Star class="h-3.5 w-3.5" />
            </button>
            <button
              v-if="!t.is_primary"
              type="button"
              class="p-1 text-ink-gray-4 hover:text-ink-red-6 transition-colors"
              title="Remove table"
              @click.stop="removeTable(t.table_name)"
            >
              <X class="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <div class="flex items-center gap-2">
      <!-- Theme Color Picker Pill -->
      <div class="group relative flex items-center gap-1.5 rounded-full bg-white px-2 py-1 shadow-sm ring-1 ring-outline-gray-2/60 transition-all hover:bg-surface-gray-1 hover:shadow" title="Change Theme Color">
        <input type="color" v-model="appThemeColor" class="absolute inset-0 h-full w-full cursor-pointer opacity-0 z-10" />
        <div class="h-3.5 w-3.5 rounded-full shadow-inner ring-1 ring-black/10" :style="{ backgroundColor: appThemeColor }"></div>
        <span class="text-xs font-semibold uppercase tracking-wider text-ink-gray-6 group-hover:text-ink-gray-8">{{ appThemeColor.replace('#', '') }}</span>
      </div>

      <button
        type="button"
        :disabled="uploading"
        class="inline-flex shrink-0 items-center gap-1.5 rounded-3 bg-white px-3 py-1.5 text-sm font-medium text-ink-gray-7 shadow-sm ring-1 ring-outline-gray-2/60 transition-all hover:bg-surface-gray-1 hover:text-ink-gray-9 hover:shadow disabled:cursor-not-allowed disabled:text-ink-gray-4 disabled:opacity-70"
        title="Add another table to this session"
        @click="triggerAdd"
      >
        <Plus class="h-4 w-4 text-ink-gray-5" /> 
        <span>Add Dataset</span>
      </button>
    </div>
    <input
      ref="fileInput"
      type="file"
      accept=".csv,.xlsx,.xls,.parquet,.json"
      class="hidden"
      @change="onFile"
    />
  </div>
</template>
