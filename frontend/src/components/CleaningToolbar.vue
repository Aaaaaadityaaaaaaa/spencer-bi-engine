<script setup lang="ts">
// Power BI-style transform ribbon: every cleaning op reachable as a labelled button,
// grouped by intent. Ribbon buttons open the dialog without a preset column (the
// dialog shows a column picker); the per-column ⋮ header menu is the column-scoped path.
import {
  Eraser,
  Wand2,
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
  ArrowDownToLine,
  Flag,
} from '@lucide/vue'
import { useSession } from '../composables/useSession'
import type { OpKind, OpRequest } from '../types'
import type { Component } from 'vue'

const emit = defineEmits<{ open: [req: OpRequest] }>()
const { sessionUuid } = useSession()

interface RibbonButton {
  op: OpKind
  label: string
  icon: Component
}

const groups: { name: string; buttons: RibbonButton[] }[] = [
  {
    name: 'Nulls',
    buttons: [
      { op: 'drop_null', label: 'Drop nulls', icon: Eraser },
      { op: 'impute_null', label: 'Fill nulls', icon: Wand2 },
      { op: 'fill_down', label: 'Fill down / up', icon: ArrowDownToLine },
    ],
  },
  {
    name: 'Rows',
    buttons: [
      { op: 'dedupe', label: 'Remove duplicates', icon: Copy },
      { op: 'dedupe_subset', label: 'Dedupe by key', icon: Columns3 },
      { op: 'filter_rows', label: 'Filter rows', icon: Filter },
    ],
  },
  {
    name: 'Columns',
    buttons: [
      { op: 'calculated_column', label: 'Add column', icon: Calculator },
      { op: 'rename_column', label: 'Rename', icon: Pencil },
      { op: 'cast', label: 'Cast type', icon: Type },
      { op: 'string_normalize', label: 'Normalize text', icon: RefreshCw },
      { op: 'drop_column', label: 'Drop column', icon: Trash2 },
    ],
  },
  {
    name: 'Derive',
    buttons: [
      { op: 'split_column', label: 'Split / extract', icon: Scissors },
      { op: 'date_extract', label: 'Date parts', icon: CalendarClock },
      { op: 'bin_column', label: 'Bin', icon: Boxes },
      { op: 'flag_outliers', label: 'Flag outliers', icon: Flag },
    ],
  },
]

function open(op: OpKind): void {
  emit('open', { op })
}
</script>

<template>
  <div class="flex flex-wrap items-stretch gap-x-1 gap-y-2 rounded-5 border border-outline-gray-1 bg-surface-base px-3 py-2 shadow-sm">
    <template v-for="(group, gi) in groups" :key="group.name">
      <div v-if="gi > 0" class="mx-1 w-px self-stretch bg-outline-gray-1"></div>
      <div class="flex flex-col">
        <div class="flex items-center gap-1">
          <button
            v-for="btn in group.buttons"
            :key="btn.op"
            type="button"
            class="inline-flex items-center gap-1.5 rounded-3 px-2.5 py-1.5 text-xs font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-9 disabled:cursor-not-allowed disabled:text-ink-gray-4 disabled:hover:bg-transparent"
            :disabled="!sessionUuid"
            :title="sessionUuid ? btn.label : 'Load a dataset first'"
            @click="open(btn.op)"
          >
            <component :is="btn.icon" class="h-3.5 w-3.5 shrink-0" />
            {{ btn.label }}
          </button>
        </div>
        <span class="mt-0.5 px-1 text-[10px] font-medium uppercase tracking-wide text-ink-gray-4">{{ group.name }}</span>
      </div>
    </template>
  </div>
</template>
