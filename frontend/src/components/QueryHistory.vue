<script setup lang="ts">
// Slide-down panel for the Query Engine: bookmarked (saved) queries + recent runs.
// Read-only over the useQueryHistory store; clicking a row asks the parent to load
// that SQL into the editor -- the parent (QueryConsole) owns the editor and the run.
import { Clock, Trash2 } from '@lucide/vue'
import { useQueryHistory } from '../composables/useQueryHistory'

const emit = defineEmits<{ load: [sql: string] }>()
const { history, saved, clearHistory, deleteSaved } = useQueryHistory()

// ISO -> local HH:MM. The list is recent-only, so a compact time reads better than a
// full date; an unparseable value degrades to an empty label rather than "Invalid Date".
function shortTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// First non-empty line of the SQL, for a single-line preview in the list.
function firstLine(sql: string): string {
  const line = sql
    .split('\n')
    .map((l) => l.trim())
    .find((l) => l.length > 0)
  return line ?? sql.trim()
}
</script>

<template>
  <div class="max-h-[280px] space-y-4 overflow-auto rounded-4 border border-outline-gray-1 bg-surface-gray-1 p-3">
    <!-- Saved / bookmarked queries -->
    <section>
      <h4 class="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-gray-5">Saved</h4>
      <p v-if="saved.length === 0" class="text-xs text-ink-gray-4">
        No saved queries yet — write a query and press Save.
      </p>
      <ul v-else class="space-y-1">
        <li
          v-for="q in saved"
          :key="q.id"
          class="group flex items-center gap-2 rounded-3 border border-outline-gray-1 bg-surface-base px-2.5 py-1.5"
        >
          <button
            type="button"
            class="min-w-0 flex-1 text-left"
            :title="q.sql"
            @click="emit('load', q.sql)"
          >
            <div class="truncate text-xs font-medium text-ink-gray-8">{{ q.name }}</div>
            <div class="truncate font-mono text-[11px] text-ink-gray-4">{{ firstLine(q.sql) }}</div>
          </button>
          <button
            type="button"
            class="shrink-0 rounded-2 p-1 text-ink-gray-4 opacity-0 transition-opacity hover:bg-surface-gray-2 hover:text-ink-red group-hover:opacity-100"
            title="Delete saved query"
            @click.stop="deleteSaved(q.id)"
          >
            <Trash2 class="h-3.5 w-3.5" />
          </button>
        </li>
      </ul>
    </section>

    <!-- Recent runs -->
    <section>
      <div class="mb-1.5 flex items-center justify-between">
        <h4 class="text-[11px] font-semibold uppercase tracking-wide text-ink-gray-5">Recent runs</h4>
        <button
          v-if="history.length"
          type="button"
          class="text-[11px] text-ink-gray-4 transition-colors hover:text-ink-gray-7"
          @click="clearHistory"
        >
          Clear
        </button>
      </div>
      <p v-if="history.length === 0" class="text-xs text-ink-gray-4">
        Queries you run will appear here.
      </p>
      <ul v-else class="space-y-1">
        <li
          v-for="h in history"
          :key="h.id"
          class="flex items-center gap-2 rounded-3 border border-outline-gray-1 bg-surface-base px-2.5 py-1.5"
        >
          <span
            class="mt-0.5 h-2 w-2 shrink-0 rounded-full"
            :class="h.ok ? 'bg-ink-green' : 'bg-ink-red'"
            :title="h.ok ? 'Succeeded' : 'Failed'"
          ></span>
          <button
            type="button"
            class="min-w-0 flex-1 text-left"
            :title="h.error ? h.error : h.sql"
            @click="emit('load', h.sql)"
          >
            <div class="truncate font-mono text-[11px] text-ink-gray-7">{{ firstLine(h.sql) }}</div>
            <div class="text-[10px] text-ink-gray-4">
              {{ shortTime(h.ranAt) }}
              <template v-if="h.ok && h.rowCount !== null"> · {{ h.rowCount.toLocaleString() }} rows</template>
              <template v-else-if="!h.ok"> · failed</template>
            </div>
          </button>
          <Clock class="h-3 w-3 shrink-0 text-ink-gray-3" />
        </li>
      </ul>
    </section>
  </div>
</template>
