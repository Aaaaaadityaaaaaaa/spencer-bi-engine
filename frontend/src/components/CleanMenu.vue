<script setup lang="ts">
// Single-button "Clean ▾" menu (Batch 3 / Table). A quieter alternative to the
// full CleaningToolbar ribbon: one trigger, grouped sections, the same OpKinds.
// The column-scoped ⋮ menu in DataGrid stays the column-specific path; this is
// the "I just want to fix the dataset" entry point.
//
// Why a separate component instead of mutating CleaningToolbar.vue: the ribbon is
// still useful at first-run (everything visible, no hidden affordances), and a
// future task can keep both on screen behind a "compact" toggle. Right now we
// render the menu instead of the ribbon from TableView; the ribbon file is
// untouched so it remains available as a fallback / alternate layout.
import { onBeforeUnmount, onMounted, ref } from 'vue'
import {
  Eraser,
  Wand2,
  ArrowDownToLine,
  Copy,
  Columns3,
  Filter,
  Calculator,
  Pencil,
  Type,
  RefreshCw,
  Trash2,
  Scissors,
  CalendarClock,
  Boxes,
  Flag,
  Wrench,
  ChevronDown,
} from '@lucide/vue'
import type { Component } from 'vue'
import { useSession } from '../composables/useSession'
import type { OpKind, OpRequest } from '../types'

const emit = defineEmits<{ open: [req: OpRequest] }>()
const { sessionUuid } = useSession()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

function close(): void {
  open.value = false
}
function toggle(e: MouseEvent): void {
  e.stopPropagation()
  open.value = !open.value
}
function onDocClick(e: MouseEvent): void {
  if (!root.value) return
  if (!root.value.contains(e.target as Node)) close()
}
function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape' && open.value) close()
}
onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKey)
})

interface Item { op: OpKind; label: string; icon: Component }
interface Group { name: string; items: Item[] }

const groups: Group[] = [
  {
    name: 'Nulls',
    items: [
      { op: 'drop_null', label: 'Drop nulls', icon: Eraser },
      { op: 'impute_null', label: 'Fill nulls…', icon: Wand2 },
      { op: 'fill_down', label: 'Fill down / up…', icon: ArrowDownToLine },
    ],
  },
  {
    name: 'Rows',
    items: [
      { op: 'dedupe', label: 'Remove duplicates', icon: Copy },
      { op: 'dedupe_subset', label: 'Dedupe by key…', icon: Columns3 },
      { op: 'filter_rows', label: 'Filter rows…', icon: Filter },
    ],
  },
  {
    name: 'Columns',
    items: [
      { op: 'calculated_column', label: 'Add column', icon: Calculator },
      { op: 'rename_column', label: 'Rename…', icon: Pencil },
      { op: 'cast', label: 'Cast type…', icon: Type },
      { op: 'string_normalize', label: 'Normalize text…', icon: RefreshCw },
      { op: 'drop_column', label: 'Drop column', icon: Trash2 },
    ],
  },
  {
    name: 'Derive',
    items: [
      { op: 'split_column', label: 'Split / extract…', icon: Scissors },
      { op: 'date_extract', label: 'Date parts…', icon: CalendarClock },
      { op: 'bin_column', label: 'Bin into ranges…', icon: Boxes },
      { op: 'flag_outliers', label: 'Flag outliers…', icon: Flag },
    ],
  },
]

function pick(op: OpKind): void {
  close()
  emit('open', { op })
}
</script>

<template>
  <div ref="root" class="relative inline-block">
    <button
      type="button"
      class="inline-flex items-center gap-1.5 rounded-3 border border-outline-gray-2 bg-surface-base px-3 py-1.5 text-xs font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2 disabled:cursor-not-allowed disabled:opacity-50"
      :disabled="!sessionUuid"
      :title="sessionUuid ? 'Open the cleaning menu' : 'Load a dataset first'"
      :aria-haspopup="'menu'"
      :aria-expanded="open"
      @click="toggle"
    >
      <Wrench class="h-3.5 w-3.5" />
      Clean
      <ChevronDown class="h-3 w-3" />
    </button>

    <Transition name="clean-menu">
      <div
        v-if="open"
        role="menu"
        class="absolute right-0 z-50 mt-1.5 w-56 overflow-hidden rounded-4 border border-outline-gray-2 bg-surface-base shadow-md"
      >
        <div
          v-for="(g, gi) in groups"
          :key="g.name"
        >
          <p class="px-3 pb-0.5 pt-2 text-[10px] font-medium uppercase tracking-wide text-ink-gray-4">
            {{ g.name }}
          </p>
          <button
            v-for="it in g.items"
            :key="it.op"
            type="button"
            role="menuitem"
            class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-ink-gray-8 transition-colors hover:bg-surface-gray-2"
            @click="pick(it.op)"
          >
            <component :is="it.icon" class="h-3.5 w-3.5 shrink-0 text-ink-gray-5" />
            <span class="truncate">{{ it.label }}</span>
          </button>
          <div
            v-if="gi < groups.length - 1"
            class="my-1 h-px bg-outline-gray-1"
          ></div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.clean-menu-enter-active,
.clean-menu-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.clean-menu-enter-from,
.clean-menu-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>