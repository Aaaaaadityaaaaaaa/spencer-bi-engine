<script setup lang="ts">
// The Query Engine console: NL question -> AI SQL (Review Gate) -> Run -> results.
//
// Flow, and where the 3-layer AI-SQL defense shows up on the client:
//   1. "Generate SQL" (askQuestion) drops the model's SQL INTO the editor. It is NOT
//      executed -- the editor IS the human Review Gate (defense layer 3). The user can
//      read/edit it freely before running.
//   2. "Run" (executeSql) sends whatever is in the editor. The backend re-validates
//      (layer 1, fail-closed -- catches hand-edited SQL too) and runs it in a
//      rolled-back sandbox (layer 2) before returning rows.
// Both async calls carry a uuid-staleness guard (mirrors DataGrid/ChartCanvas): if the
// session switches mid-flight, the late response is dropped instead of rendered.
import { ref, watch, computed, onActivated } from 'vue'
import { Sparkles, Play, Loader2, AlertCircle, Bookmark, Clock, Check, X, Info, Zap, Wrench } from '@lucide/vue'
import { useSession } from '../composables/useSession'
import { useQueryHistory } from '../composables/useQueryHistory'
import { useQuestionHandoff } from '../composables/useQuestionHandoff'
import { askQuestion, sqlAssist, executeSql, apiErrorMessage } from '../services/api'
import type { AskTurn, SqlAssistMode, ExecuteResultResponse } from '../types'
import SqlEditor from './SqlEditor.vue'
import ResultsTable from './ResultsTable.vue'
import QueryHistory from './QueryHistory.vue'

const { sessionUuid, tableName, columns } = useSession()
const { recordRun, saveQuery } = useQueryHistory()
const { pendingQuestion, takePendingQuestion } = useQuestionHandoff()

const question = ref('')
const sqlText = ref('')
// Handle to the editor so the schema chips can insert names at the cursor.
const editor = ref<InstanceType<typeof SqlEditor> | null>(null)

// Pre-seed the editor with a starter query so the long, UUID-laden table name never
// has to be typed. Only seeds when the editor is empty or still holds a prior auto-seed
// -- SQL the user wrote or generated is never clobbered (including across a dataset
// swap, where the stale seed is replaced but hand-written SQL is left alone).
const seeded = ref('')
watch(
  [sessionUuid, tableName],
  ([uuid, table]) => {
    if (!uuid || !table) return
    const starter = `SELECT *\nFROM ${table}\nLIMIT 100;`
    if (sqlText.value === '' || sqlText.value === seeded.value) {
      sqlText.value = starter
      seeded.value = starter
    }
  },
  { immediate: true },
)

// Click-to-insert from the schema chips (table name / column names).
function insertToken(text: string | null): void {
  if (!text) return
  editor.value?.insert(text)
}

const asking = ref(false)
const running = ref(false)
const askError = ref<string | null>(null)
const runError = ref<string | null>(null)
// Non-null after a successful /ask: shows whether the SQL came from cache and how many
// self-correction passes the model needed.
const askMeta = ref<{ cacheHit: boolean; retries: number } | null>(null)
const result = ref<ExecuteResultResponse | null>(null)

// #21 conversational refinement: the running (question -> SQL) conversation. Each
// successful generate appends a turn; the next generate replays the last MAX_TURNS as
// history so "now group by month" refines the previous query. Kept-alive preserves it
// across tab switches; a session switch clears it. "Start fresh" resets the thread.
const MAX_TURNS = 6
const turns = ref<AskTurn[]>([])
const refineCount = computed(() => turns.value.length)

// #22 SQL assist (explain / fix / optimize). `assistMode` is the in-flight action (null
// when idle); the explanation panel shows the returned prose. fix/optimize also drop NEW
// validated SQL into the editor (the Review Gate — the user still clicks Run).
const assistMode = ref<SqlAssistMode | null>(null)
const assistError = ref<string | null>(null)
const assistPanel = ref<{ mode: SqlAssistMode; text: string; retries: number } | null>(null)

const ASSIST_TITLE: Record<SqlAssistMode, string> = {
  explain: 'What this query does',
  fix: 'Fixed the query',
  optimize: 'Optimized the query',
}

// History / saved-query UI state.
const showHistory = ref(false)
const savingName = ref<string | null>(null) // non-null => the inline "name this query" input is open

// NL -> SQL. Drops the result into the editor (the Review Gate); never auto-runs.
// #21: replays the recent conversation so a follow-up refines the last query, and records
// each successful (question, sql) turn to build on next time.
async function generate(): Promise<void> {
  const uuid = sessionUuid.value
  const q = question.value.trim()
  if (!uuid || !q || asking.value) return
  asking.value = true
  askError.value = null
  askMeta.value = null
  assistPanel.value = null // a fresh generation makes any prior explanation stale
  const history = turns.value.slice(-MAX_TURNS)
  try {
    const res = await askQuestion(uuid, q, history)
    if (uuid !== sessionUuid.value) return // session switched mid-flight -> drop
    sqlText.value = res.sql
    askMeta.value = { cacheHit: res.cache_hit, retries: res.retries_used }
    turns.value = [...turns.value, { question: q, sql: res.sql }]
  } catch (e) {
    if (uuid === sessionUuid.value) askError.value = apiErrorMessage(e)
  } finally {
    if (uuid === sessionUuid.value) asking.value = false
  }
}

// #21: drop the conversation so the next question starts cold (no history threaded).
function startFresh(): void {
  turns.value = []
  askMeta.value = null
}

// Run the (reviewed) SQL. The backend validates + sandboxes; here we just render rows.
async function run(): Promise<void> {
  const uuid = sessionUuid.value
  const sql = sqlText.value.trim()
  if (!uuid || !sql || running.value) return
  running.value = true
  runError.value = null
  try {
    const res = await executeSql(uuid, sql)
    if (uuid !== sessionUuid.value) return
    result.value = res
    recordRun({ sql, ok: true, rowCount: res.row_count })
  } catch (e) {
    if (uuid === sessionUuid.value) {
      const msg = apiErrorMessage(e)
      runError.value = msg
      result.value = null
      recordRun({ sql, ok: false, error: msg })
    }
  } finally {
    if (uuid === sessionUuid.value) running.value = false
  }
}

// #22: explain / fix / optimize the SQL currently in the editor. explain returns prose;
// fix/optimize drop a NEW validated SELECT into the editor (Review Gate — the user runs
// it). `fix` sends the last run error as context so the model knows what to repair.
async function assist(mode: SqlAssistMode): Promise<void> {
  const uuid = sessionUuid.value
  const sql = sqlText.value.trim()
  if (!uuid || !sql || assistMode.value) return
  assistMode.value = mode
  assistError.value = null
  try {
    const res = await sqlAssist(uuid, mode, sql, mode === 'fix' ? runError.value : null)
    if (uuid !== sessionUuid.value) return // session switched mid-flight -> drop
    assistPanel.value = { mode, text: res.explanation, retries: res.retries_used }
    if (res.sql) {
      sqlText.value = res.sql // Review Gate: never auto-run
      if (mode === 'fix') runError.value = null // the prior error no longer applies
    }
  } catch (e) {
    if (uuid === sessionUuid.value) assistError.value = apiErrorMessage(e)
  } finally {
    if (uuid === sessionUuid.value) assistMode.value = null
  }
}

// #26: a suggested question handed over from the co-located Suggested Questions strip.
// Two entry points, both funnelling through the read-and-clear consumePending():
//   - watch(pendingQuestion): the strip is a SIBLING on this view, so clicking a
//     suggestion while the console is already active won't re-fire onActivated — the
//     watch catches that in-view case.
//   - onActivated: covers the first mount / any keep-alive re-insertion (e.g. a handoff
//     set just before navigating here). Whichever runs first consumes it; the other
//     then reads null. A handed-over question starts a fresh conversation.
function consumePending(): void {
  const q = takePendingQuestion()
  if (!q) return
  startFresh()
  question.value = q
  void generate()
}
watch(pendingQuestion, (q) => {
  if (q) consumePending()
})
onActivated(consumePending)

// A session switch (or "Replace dataset") invalidates the whole console: drop the
// conversation, the last result, and any transient meta / error / assist state.
watch(sessionUuid, () => {
  turns.value = []
  result.value = null
  askMeta.value = null
  askError.value = null
  runError.value = null
  assistPanel.value = null
  assistError.value = null
})

// Load a saved/recent query's SQL into the editor. An explicit user choice, so it
// overwrites freely; because the new text differs from `seeded`, the auto-seed watch
// above will not clobber it on the next tick.
function loadSql(sql: string): void {
  sqlText.value = sql
  showHistory.value = false
}

// Inline "save this query" flow: open with a sensible default name (the NL question if
// there was one, else the first line of the SQL), then confirm to persist.
function startSave(): void {
  if (!sqlText.value.trim()) return
  const q = question.value.trim()
  const fallback = sqlText.value.trim().split('\n')[0].slice(0, 40)
  savingName.value = q || fallback || 'Query'
}
function confirmSave(): void {
  const name = (savingName.value ?? '').trim()
  if (name && sqlText.value.trim()) saveQuery(name, sqlText.value)
  savingName.value = null
}
function cancelSave(): void {
  savingName.value = null
}
</script>

<template>
  <div class="overflow-hidden rounded-5 border border-outline-gray-1 bg-surface-base shadow-sm">
    <div class="border-b border-outline-gray-1 bg-surface-gray-1 px-4 py-3">
      <h3 class="text-sm font-semibold text-ink-gray-8">Query Engine</h3>
      <p class="mt-0.5 text-xs text-ink-gray-5">
        Ask in plain English to generate SQL, review it, then run — or write SQL directly.
      </p>
    </div>

    <div class="space-y-4 p-4">
      <!-- AI ask row -->
      <div>
        <div class="flex gap-2">
          <div class="relative flex-1">
            <Sparkles class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-primary" />
            <input
              v-model="question"
              type="text"
              placeholder="e.g., total amount by category, top 10"
              class="w-full rounded-4 border border-outline-gray-2 bg-surface-gray-2 py-2 pl-8 pr-3 text-sm text-ink-gray-8 placeholder-ink-gray-4 transition-colors hover:bg-surface-gray-3 focus:border-outline-gray-4 focus:bg-surface-base focus:outline-none"
              @keydown.enter="generate"
            />
          </div>
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-3 bg-primary px-4 py-2 text-sm font-medium text-ink-white shadow-sm transition-colors hover:bg-primary-7 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="asking || !question.trim()"
            @click="generate"
          >
            <Loader2 v-if="asking" class="h-4 w-4 animate-spin" />
            <Sparkles v-else class="h-4 w-4" />
            Generate SQL
          </button>
        </div>
        <div class="mt-1.5 flex min-h-[16px] flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          <span v-if="askMeta" class="text-ink-gray-5">
            SQL generated<template v-if="askMeta.cacheHit"> · from cache</template>
            <template v-else-if="askMeta.retries > 0">
              · self-corrected {{ askMeta.retries }}×
            </template>
          </span>
          <span v-if="refineCount > 0" class="inline-flex items-center gap-1 text-ink-gray-5">
            <span class="text-ink-gray-4">·</span>
            building on {{ refineCount }} question<template v-if="refineCount > 1">s</template>
            <button
              type="button"
              class="ml-0.5 rounded-2 px-1 py-0.5 text-[11px] font-medium text-primary transition-colors hover:bg-primary-1"
              title="Start a fresh conversation — drop the refinement history"
              @click="startFresh"
            >
              Start fresh
            </button>
          </span>
          <span v-if="askError" class="inline-flex items-center gap-1 text-ink-red">
            <AlertCircle class="h-3.5 w-3.5" /> {{ askError }}
          </span>
        </div>
      </div>

      <!-- Single-table schema reference (ADR-006): click any chip to insert it. -->
      <div v-if="tableName || columns.length" class="space-y-1.5">
        <div v-if="tableName" class="flex flex-wrap items-center gap-1.5">
          <span class="text-[11px] font-medium uppercase tracking-wide text-ink-gray-4">Table</span>
          <button
            type="button"
            class="rounded-2 border border-outline-gray-2 bg-surface-gray-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-gray-7 transition-colors hover:bg-surface-gray-3 hover:text-ink-gray-8"
            title="Click to insert the table name"
            @mousedown.prevent
            @click="insertToken(tableName)"
          >
            {{ tableName }}
          </button>
        </div>
        <div v-if="columns.length" class="flex flex-wrap items-center gap-1.5">
          <span class="text-[11px] font-medium uppercase tracking-wide text-ink-gray-4">Columns</span>
          <button
            v-for="col in columns"
            :key="col.name"
            type="button"
            class="rounded-2 bg-surface-gray-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-gray-7 transition-colors hover:bg-surface-gray-3 hover:text-ink-gray-8"
            :title="`${col.type} — click to insert`"
            @mousedown.prevent
            @click="insertToken(col.name)"
          >
            {{ col.name }}
          </button>
        </div>
      </div>

      <!-- SQL editor (the Review Gate) + run bar -->
      <div class="space-y-2">
        <SqlEditor
          ref="editor"
          v-model:sql="sqlText"
          :read-only="running"
          :table-name="tableName"
          :columns="columns"
        />
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="inline-flex items-center gap-1 rounded-3 border border-outline-gray-2 bg-surface-base px-2.5 py-1.5 text-xs font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
              :class="{ 'bg-surface-gray-2 text-ink-gray-9': showHistory }"
              title="Show recent runs and saved queries"
              @click="showHistory = !showHistory"
            >
              <Clock class="h-3.5 w-3.5" /> History
            </button>
            <button
              type="button"
              class="inline-flex items-center gap-1 rounded-3 border border-outline-gray-2 bg-surface-base px-2.5 py-1.5 text-xs font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!sqlText.trim()"
              title="Save this query"
              @click="startSave"
            >
              <Bookmark class="h-3.5 w-3.5" /> Save
            </button>
            <!-- #22 AI assists on the editor's SQL. Explain returns prose; Optimize drops a
                 faster equivalent into the editor (still the Review Gate — never auto-run). -->
            <button
              type="button"
              class="inline-flex items-center gap-1 rounded-3 border border-outline-gray-2 bg-surface-base px-2.5 py-1.5 text-xs font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!sqlText.trim() || assistMode !== null"
              title="Explain what this SQL does"
              @click="assist('explain')"
            >
              <Loader2 v-if="assistMode === 'explain'" class="h-3.5 w-3.5 animate-spin text-primary" />
              <Info v-else class="h-3.5 w-3.5" /> Explain
            </button>
            <button
              type="button"
              class="inline-flex items-center gap-1 rounded-3 border border-outline-gray-2 bg-surface-base px-2.5 py-1.5 text-xs font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!sqlText.trim() || assistMode !== null"
              title="Suggest a faster or cleaner equivalent"
              @click="assist('optimize')"
            >
              <Loader2 v-if="assistMode === 'optimize'" class="h-3.5 w-3.5 animate-spin text-primary" />
              <Zap v-else class="h-3.5 w-3.5" /> Optimize
            </button>
            <span class="hidden text-[11px] text-ink-gray-4 lg:inline">⌘/Ctrl + Enter to run</span>
          </div>
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-3 border border-outline-gray-2 bg-surface-base px-4 py-1.5 text-sm font-medium text-ink-gray-8 shadow-sm transition-colors hover:bg-surface-gray-2 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="running || !sqlText.trim()"
            @click="run"
          >
            <Loader2 v-if="running" class="h-4 w-4 animate-spin text-primary" />
            <Play v-else class="h-4 w-4 text-primary" />
            Run
          </button>
        </div>

        <!-- Inline "name this query" input (opened by Save) -->
        <div
          v-if="savingName !== null"
          class="flex items-center gap-2 rounded-3 border border-outline-gray-2 bg-surface-gray-1 px-2 py-1.5"
        >
          <Bookmark class="h-3.5 w-3.5 shrink-0 text-primary" />
          <input
            v-model="savingName"
            type="text"
            placeholder="Name this query"
            class="min-w-0 flex-1 bg-transparent text-sm text-ink-gray-8 placeholder-ink-gray-4 focus:outline-none"
            @keydown.enter="confirmSave"
            @keydown.esc="cancelSave"
          />
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded-2 bg-primary px-2 py-1 text-xs font-medium text-ink-white transition-colors hover:bg-primary-7 disabled:opacity-50"
            :disabled="!savingName?.trim()"
            @click="confirmSave"
          >
            <Check class="h-3.5 w-3.5" /> Save
          </button>
          <button
            type="button"
            class="rounded-2 p-1 text-ink-gray-4 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-7"
            title="Cancel"
            @click="cancelSave"
          >
            <X class="h-3.5 w-3.5" />
          </button>
        </div>

        <QueryHistory v-if="showHistory" @load="loadSql" />
      </div>

      <!-- #22 AI-assist explanation (explain / fix / optimize). fix & optimize also dropped
           new SQL into the editor above; this panel carries the prose + self-correction count. -->
      <div
        v-if="assistPanel"
        class="rounded-4 border border-primary-2 bg-primary-1 p-3 text-sm text-ink-gray-8"
      >
        <div class="mb-1 flex items-center justify-between gap-2">
          <span class="inline-flex items-center gap-1.5 text-xs font-semibold text-primary">
            <Sparkles class="h-3.5 w-3.5" />
            {{ ASSIST_TITLE[assistPanel.mode] }}
            <span v-if="assistPanel.retries > 0" class="font-normal text-ink-gray-5">
              · self-corrected {{ assistPanel.retries }}×
            </span>
          </span>
          <button
            type="button"
            class="rounded-2 p-0.5 text-ink-gray-4 transition-colors hover:bg-surface-base hover:text-ink-gray-7"
            title="Dismiss"
            @click="assistPanel = null"
          >
            <X class="h-3.5 w-3.5" />
          </button>
        </div>
        <p class="whitespace-pre-wrap break-words leading-relaxed">{{ assistPanel.text }}</p>
      </div>
      <div
        v-if="assistError"
        class="flex items-start gap-2 rounded-4 border border-outline-gray-2 bg-surface-gray-1 p-3 text-sm text-ink-red"
      >
        <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
        <span class="break-words">{{ assistError }}</span>
      </div>

      <!-- Results / error -->
      <div
        v-if="runError"
        class="rounded-4 border border-outline-gray-2 bg-surface-gray-1 p-3 text-sm"
      >
        <div class="flex items-start gap-2 text-ink-red">
          <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
          <span class="break-words">{{ runError }}</span>
        </div>
        <!-- #22 one-click repair: send the SQL + this error to the model, get a fixed
             SELECT back into the editor for review (never auto-run). -->
        <button
          type="button"
          class="mt-2 inline-flex items-center gap-1.5 rounded-3 bg-primary px-3 py-1.5 text-xs font-medium text-ink-white shadow-sm transition-colors hover:bg-primary-7 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="assistMode !== null || !sqlText.trim()"
          title="Ask AI to fix this query"
          @click="assist('fix')"
        >
          <Loader2 v-if="assistMode === 'fix'" class="h-3.5 w-3.5 animate-spin" />
          <Wrench v-else class="h-3.5 w-3.5" />
          Fix with AI
        </button>
      </div>
      <ResultsTable
        v-else-if="result"
        :columns="result.columns"
        :rows="result.rows"
        :truncated="result.truncated"
        :session-uuid="sessionUuid"
      />
      <div v-else class="rounded-4 border border-dashed border-outline-gray-2 py-8 text-center text-xs text-ink-gray-4">
        Run a query to see results.
      </div>
    </div>
  </div>
</template>
