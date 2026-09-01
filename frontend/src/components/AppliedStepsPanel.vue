<script setup lang="ts">
import {
  History,
  FileUp,
  X,
  Eraser,
  Pencil,
  Copy,
  Scissors,
  Calculator,
  Type,
  Filter,
  RefreshCw,
  Trash2,
  CalendarClock,
  Boxes,
  ArrowDownToLine,
  Flag,
  Wand2
} from '@lucide/vue'
import { useSession } from '../composables/useSession'

const { historySteps, currentStepIndex, gotoStep, applying, toggleAppliedSteps } = useSession()

// Map internal op names to readable labels and icons
function getStepInfo(op: string, column: string | null) {
  const map: Record<string, { label: string; icon: any }> = {
    'initial': { label: 'Uploaded File', icon: FileUp },
    'drop_null': { label: 'Remove Empty Rows', icon: Eraser },
    'impute_null': { label: 'Fill Missing Values', icon: Pencil },
    'rename_column': { label: 'Rename Column', icon: Type },
    'drop_column': { label: 'Remove Column', icon: Trash2 },
    'cast': { label: 'Change Data Type', icon: RefreshCw },
    'calculated_column': { label: 'Add Custom Column', icon: Calculator },
    'filter_rows': { label: 'Filter Rows', icon: Filter },
    'dedupe': { label: 'Remove Duplicates', icon: Copy },
    'dedupe_subset': { label: 'Remove Duplicates', icon: Copy },
    'string_normalize': { label: 'Clean Text', icon: Wand2 },
    'split_column': { label: 'Split Column', icon: Scissors },
    'date_extract': { label: 'Extract Date Part', icon: CalendarClock },
    'bin_column': { label: 'Group into Bins', icon: Boxes },
    'fill_down': { label: 'Fill Down', icon: ArrowDownToLine },
    'flag_outliers': { label: 'Detect Outliers', icon: Flag },
    'absolute_value': { label: 'Absolute Value', icon: Calculator },
    'update_cell': { label: 'Edit Cell', icon: Pencil },
  }
  
  // Fix Wand2 missing import by using Pencil as fallback if not in map, or just import it.
  const info = map[op] || { label: op, icon: History }
  
  if (column && op !== 'initial') {
    return { ...info, label: `${info.label} (${column})` }
  }
  return info
}
</script>

<template>
  <div class="flex h-full w-64 flex-col rounded-md border border-outline-gray-1 bg-surface-base shadow-sm">
    <div class="flex items-center justify-between border-b border-outline-gray-1 bg-surface-gray-1 px-4 py-3">
      <div class="flex items-center gap-2">
        <History class="h-4 w-4 text-ink-gray-5" />
        <h3 class="text-sm font-semibold text-ink-gray-8">Applied Steps</h3>
      </div>
      <button @click="toggleAppliedSteps" class="rounded hover:bg-outline-gray-2 p-1 text-ink-gray-5 transition-colors">
        <X class="h-4 w-4" />
      </button>
    </div>
    <div class="flex-1 overflow-y-auto p-2">
      <div v-if="historySteps.length === 0" class="p-4 text-center text-xs text-ink-gray-5">
        No steps applied yet.
      </div>
      <div v-else class="space-y-1 relative">
        <!-- Connecting line -->
        <div class="absolute left-4 top-4 bottom-4 w-px bg-outline-gray-2 z-0" />
        
        <button
          v-for="(step, idx) in historySteps"
          :key="idx"
          type="button"
          class="relative z-10 flex w-full items-center gap-3 rounded-md px-3 py-2 text-left transition-colors"
          :class="[
            idx === currentStepIndex
              ? 'bg-primary-1 text-primary'
              : idx > currentStepIndex
                ? 'text-ink-gray-4 opacity-60'
                : 'text-ink-gray-8 hover:bg-surface-gray-2'
          ]"
          :disabled="applying"
          @click="gotoStep(idx)"
          :title="idx > currentStepIndex ? 'Step undone. Click to redo.' : 'Click to revert back to this step.'"
        >
          <div 
            class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border bg-surface-base"
            :class="idx === currentStepIndex ? 'border-primary text-primary' : 'border-outline-gray-3 text-ink-gray-5'"
          >
            <component :is="getStepInfo(step.op, step.column).icon" class="h-3.5 w-3.5" />
          </div>
          <div class="min-w-0 flex-1">
            <p class="truncate text-xs font-medium" :class="{'font-bold': idx === currentStepIndex}">
              {{ getStepInfo(step.op, step.column).label }}
            </p>
          </div>
        </button>
      </div>
    </div>
  </div>
</template>
