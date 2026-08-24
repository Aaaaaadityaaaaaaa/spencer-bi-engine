<script setup lang="ts">
// #26 Auto-EDA: as soon as a dataset is loaded, offer a handful of analytical questions
// inferred from its schema. Lives in the Query Engine section: clicking one hands it to
// the co-located QueryConsole (useQuestionHandoff) which fills the NL box + generates SQL.
// The questions are cached per schema_version server-side, so a transform regenerates them
// but a revisit is free.
import { ref, watch } from 'vue'
import { Sparkles, Loader2, AlertCircle, ArrowRight, RefreshCw, ChevronDown, ChevronRight } from '@lucide/vue'
import { useSession } from '../composables/useSession'
import { useQuestionHandoff } from '../composables/useQuestionHandoff'
import { suggestQuestions, apiErrorMessage } from '../services/api'

const { sessionUuid, dataVersion } = useSession()
const { askInQueryEngine } = useQuestionHandoff()

const questions = ref<string[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
// Collapsible: open by default (the questions are a primary call-to-action), but the
// card can be folded to a single header row to reclaim vertical space. Toggled by hand,
// never automatically, so the user's choice sticks while they work.
const expanded = ref(true)

async function load(): Promise<void> {
  const uuid = sessionUuid.value
  if (!uuid || loading.value) return
  loading.value = true
  error.value = null
  try {
    const res = await suggestQuestions(uuid)
    if (uuid !== sessionUuid.value) return // session switched mid-flight -> drop
    questions.value = res.questions
  } catch (e) {
    if (uuid === sessionUuid.value) {
      error.value = apiErrorMessage(e)
      questions.value = []
    }
  } finally {
    if (uuid === sessionUuid.value) loading.value = false
  }
}

// Auto-load when a dataset appears, and re-load after a transform (dataVersion bump)
// since the schema — and therefore the useful questions — may have changed. The server
// cache keeps the repeat calls cheap.
watch(
  [sessionUuid, dataVersion],
  () => {
    if (sessionUuid.value) void load()
    else {
      questions.value = []
      error.value = null
    }
  },
  { immediate: true },
)

// Hand the question to the co-located QueryConsole; its watch on the handoff picks it
// up, fills the NL box and generates SQL. No navigation — we're already in the Engine.
function ask(q: string): void {
  askInQueryEngine(q)
}
</script>

<template>
  <div class="overflow-hidden rounded-5 border border-outline-gray-1 bg-surface-base shadow-sm">
    <div class="flex items-center justify-between gap-3 border-b border-outline-gray-1 bg-surface-gray-1 px-4 py-3">
      <button
        type="button"
        class="flex min-w-0 flex-1 items-center gap-2 text-left"
        :aria-expanded="expanded"
        @click="expanded = !expanded"
      >
        <component :is="expanded ? ChevronDown : ChevronRight" class="h-4 w-4 shrink-0 text-ink-gray-4" />
        <div class="min-w-0">
          <h3 class="flex items-center gap-1.5 text-sm font-semibold text-ink-gray-8">
            <Sparkles class="h-4 w-4 shrink-0 text-primary" /> Suggested questions
            <span
              v-if="questions.length"
              class="rounded-full bg-surface-gray-2 px-1.5 py-0.5 text-[10px] font-medium text-ink-gray-5"
            >{{ questions.length }}</span>
          </h3>
          <p class="mt-0.5 truncate text-xs text-ink-gray-5">
            AI-suggested starting points — click one to drop it into the console below.
          </p>
        </div>
      </button>
      <button
        type="button"
        class="inline-flex shrink-0 items-center gap-1 rounded-3 border border-outline-gray-2 bg-surface-base px-2.5 py-1.5 text-xs font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="loading"
        title="Regenerate suggestions"
        @click="load"
      >
        <RefreshCw class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" /> Refresh
      </button>
    </div>

    <div v-show="expanded" class="p-4">
      <div v-if="loading && questions.length === 0" class="flex items-center gap-2 py-2 text-sm text-ink-gray-5">
        <Loader2 class="h-4 w-4 animate-spin text-primary" /> Analyzing your data…
      </div>

      <div
        v-else-if="error"
        class="flex items-start gap-2 rounded-4 border border-outline-gray-2 bg-surface-gray-1 p-3 text-sm text-ink-red"
      >
        <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
        <span class="break-words">{{ error }}</span>
      </div>

      <ul v-else-if="questions.length" class="space-y-1.5">
        <li v-for="(q, i) in questions" :key="i">
          <button
            type="button"
            class="group flex w-full items-center gap-2 rounded-3 border border-outline-gray-2 bg-surface-gray-1 px-3 py-2 text-left text-sm text-ink-gray-8 transition-colors hover:border-primary-3 hover:bg-primary-1"
            @click="ask(q)"
          >
            <Sparkles class="h-3.5 w-3.5 shrink-0 text-primary" />
            <span class="min-w-0 flex-1">{{ q }}</span>
            <ArrowRight class="h-3.5 w-3.5 shrink-0 text-ink-gray-4 transition-colors group-hover:text-primary" />
          </button>
        </li>
      </ul>

      <p v-else class="py-2 text-xs text-ink-gray-4">No suggestions available.</p>
    </div>
  </div>
</template>
