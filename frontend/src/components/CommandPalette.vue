<script setup lang="ts">
// Global command palette (Batch 1 / Global). Opens on Cmd/Ctrl-K (and the "Search"
// affordance), fuzzy-searches a static action registry, and runs the chosen action.
// Additive: lives at the app root, mounted by App.vue. Actions are plain callbacks so
// this stays decoupled from any view logic.
import { computed, ref, watch } from 'vue'
import { Search, CornerDownLeft, ArrowUp, ArrowDown } from '@lucide/vue'

export interface Command {
  id: string
  label: string
  hint?: string
  group?: string
  run: () => void
}

const props = defineProps<{ commands: Command[] }>()
const emit = defineEmits<{ close: [] }>()

const open = defineModel<boolean>('open', { default: false })
const query = ref('')
const active = ref(0)

const filtered = computed<Command[]>(() => {
  const q = query.value.trim().toLowerCase()
  const list = !q
    ? props.commands
    : props.commands.filter(
        (c) =>
          c.label.toLowerCase().includes(q) ||
          c.hint?.toLowerCase().includes(q) ||
          c.group?.toLowerCase().includes(q),
      )
  return list
})

watch(filtered, () => { active.value = 0 })

function choose(cmd?: Command) {
  const c = cmd ?? filtered.value[active.value]
  if (!c) return
  open.value = false
  c.run()
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') { open.value = false; return }
  if (e.key === 'ArrowDown') { e.preventDefault(); active.value = Math.min(active.value + 1, filtered.value.length - 1); return }
  if (e.key === 'ArrowUp') { e.preventDefault(); active.value = Math.max(active.value - 1, 0); return }
  if (e.key === 'Enter') { e.preventDefault(); choose(); return }
}

// NOTE: the Cmd/Ctrl-K shortcut is owned by App.vue (single source of truth) so the
// header button and the keyboard stay in sync. This component only handles navigation
// keys while it is open (Escape / arrows / Enter), bound on the input below.
watch(open, (v) => { if (v) { query.value = ''; active.value = 0; setTimeout(() => document.getElementById('palette-input')?.focus(), 30) } })

// Grouped view for rendering. `index` is the position inside the FLAT `filtered`
// list so hover and keyboard selection agree (they share one `active` pointer).
const groups = computed(() => {
  const map = new Map<string, { cmd: Command; index: number }[]>()
  filtered.value.forEach((c, index) => {
    const g = c.group ?? 'Actions'
    if (!map.has(g)) map.set(g, [])
    map.get(g)!.push({ cmd: c, index })
  })
  return [...map.entries()]
})
</script>

<template>
  <Transition name="fade">
    <div
      v-if="open"
      class="fixed inset-0 z-[60] flex items-start justify-center bg-surface-scrim px-4 pt-[12vh]"
      @click.self="open = false"
      @keydown="onKey"
    >
      <div
        class="w-full max-w-lg overflow-hidden rounded-6 border border-outline-gray-2 bg-surface-base shadow-md"
        role="dialog"
        aria-label="Command palette"
      >
        <div class="flex items-center gap-2 border-b border-outline-gray-1 px-3 py-2.5">
          <Search class="h-4 w-4 shrink-0 text-ink-gray-4" />
          <input
            id="palette-input"
            v-model="query"
            type="text"
            placeholder="Search actions, tables, views…"
            class="w-full bg-transparent text-sm text-ink-gray-9 outline-none placeholder:text-ink-gray-4"
            @keydown="onKey"
          />
          <kbd class="rounded-2 border border-outline-gray-2 px-1.5 py-0.5 text-[10px] text-ink-gray-4">ESC</kbd>
        </div>

        <div class="max-h-80 overflow-y-auto py-1">
          <template v-for="[group, cmds] in groups" :key="group">
            <p class="px-3 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-ink-gray-4">{{ group }}</p>
            <button
              v-for="entry in cmds"
              :key="entry.cmd.id"
              type="button"
              data-palette-item
              class="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm transition-colors"
              :class="entry.index === active ? 'bg-surface-gray-2 text-ink-gray-9' : 'text-ink-gray-7 hover:bg-surface-gray-1'"
              @mouseenter="active = entry.index"
              @click="choose(entry.cmd)"
            >
              <span class="truncate">{{ entry.cmd.label }}</span>
              <span v-if="entry.cmd.hint" class="shrink-0 text-[11px] text-ink-gray-4">{{ entry.cmd.hint }}</span>
            </button>
          </template>
          <p v-if="filtered.length === 0" class="px-3 py-6 text-center text-sm text-ink-gray-4">
            No matches — try a different keyword.
          </p>
        </div>

        <div class="flex items-center gap-3 border-t border-outline-gray-1 px-3 py-1.5 text-[11px] text-ink-gray-4">
          <span class="flex items-center gap-1"><ArrowUp class="h-3 w-3" /><ArrowDown class="h-3 w-3" /> navigate</span>
          <span class="flex items-center gap-1"><CornerDownLeft class="h-3 w-3" /> select</span>
          <span class="ml-auto">Spencer</span>
        </div>
      </div>
    </div>
  </Transition>
</template>
