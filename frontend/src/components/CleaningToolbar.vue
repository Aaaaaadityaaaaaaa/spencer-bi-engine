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
  PanelRightOpen,
} from '@lucide/vue'
import { useSession } from '../composables/useSession'
import type { OpKind, OpRequest } from '../types'
import type { Component } from 'vue'

const emit = defineEmits<{ open: [req: OpRequest] }>()
const { sessionUuid, showAppliedSteps, toggleAppliedSteps } = useSession()

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
  <div class="flex flex-wrap items-stretch gap-2 rounded-md border border-outline-gray-2 bg-surface-base px-2 py-2 shadow-sm relative z-10 transition-all hover:shadow-md ">
    <template v-for="(group, gi) in groups" :key="group.name">
      <div v-if="gi > 0" class="mx-2 w-px shrink-0 self-stretch bg-gradient-to-b from-transparent via-primary-5/50 to-transparent shadow-[0_0_1px_var(--primary-5)] opacity-70"></div>
      <div class="flex flex-col shrink-0">
        <div class="flex items-start gap-1">
          <button
            v-for="btn in group.buttons"
            :key="btn.op"
            type="button"
            class="group flex flex-col items-center justify-start gap-1.5 rounded-xl border border-primary-2 px-2 py-2 w-24 h-[4.5rem] text-center transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-surface-gray-2 hover:shadow-sm disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:bg-transparent disabled:hover:shadow-none"
            :disabled="!sessionUuid"
            :title="sessionUuid ? btn.label : 'Load a dataset first'"
            @click="open(btn.op)"
          >
            <component :is="btn.icon" class="h-5 w-5 shrink-0 text-ink-gray-5 transition-colors group-hover:text-primary-6" />
            <span class="text-[10px] font-semibold leading-tight text-ink-gray-7 group-hover:text-ink-gray-9">{{ btn.label }}</span>
          </button>
        </div>
        <div class="mt-1 flex justify-center pb-1">
          <span class="text-[9px] font-bold uppercase tracking-wider text-ink-gray-4/80">{{ group.name }}</span>
        </div>
      </div>
    </template>

    <div class="ml-auto flex shrink-0 items-center border-l-0 pl-0 mt-2 w-full justify-center sm:border-l sm:pl-2 sm:w-auto sm:mt-0 sm:justify-start border-outline-gray-2 pl-2">
      <button 
        @click="toggleAppliedSteps"
        class="flex flex-col items-center justify-center gap-1.5 rounded-xl border border-primary-2 px-3 py-2 w-20 h-[4.5rem] text-center transition-all duration-300 ease-out hover:-translate-y-0.5 hover:shadow-sm"
        :class="showAppliedSteps ? 'text-primary bg-primary-1/50 hover:bg-primary-1' : 'text-ink-gray-5 hover:bg-surface-gray-2'"
        title="Toggle Applied Steps"
      >
        <PanelRightOpen class="h-5 w-5 shrink-0 transition-colors" :class="showAppliedSteps ? 'text-primary' : 'group-hover:text-ink-gray-9'" />
        <span class="text-[10px] font-semibold leading-tight" :class="showAppliedSteps ? 'text-primary' : 'text-ink-gray-7 group-hover:text-ink-gray-9'">Steps</span>
      </button>
    </div>
  </div>
</template>


