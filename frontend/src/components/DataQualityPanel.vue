<script setup lang="ts">
// Read-only whole-table data-quality scan (TASK-016) -- the companion to the column
// profiler. Mounted inline in the Table workspace as a COLLAPSIBLE CARD (not a drawer):
// on session load and after every transform it calls GET /quality and renders a
// severity-ranked list of findings. Each finding that maps to an OpKind gets a one-click
// Fix that emits an OpRequest; the parent opens the existing OpDialog (dry-run preview
// then apply), so this component never mutates data. It imports NO charting library --
// the Table bundle stays ECharts-free (everything here is CSS + Lucide icons).
import { ref, computed, watch } from 'vue'
import {
  ShieldCheck,
  ShieldAlert,
  ChevronDown,
  ChevronRight,
  Wrench,
  Loader2,
  AlertCircle,
  EyeOff,
  Eye,
  RotateCcw,
} from '@lucide/vue'
import { useSession } from '../composables/useSession'
import { fetchQualityReport, apiErrorMessage } from '../services/api'
import type { OpRequest, QualityReport, QualityFinding, QualitySeverity } from '../types'

const emit = defineEmits<{
  fix: [req: OpRequest]
  profile: [column: string]
}>()

// sessionUuid identifies the target; dataVersion bumps on every transform/undo/redo,
// so applying a Fix re-runs the scan and the resolved finding disappears.
const { sessionUuid, tableName, dataVersion } = useSession()

const report = ref<QualityReport | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const expanded = ref(false)
// The auto-expand default (open when a high/medium issue exists) applies only until the
// user manually toggles the card; after that their choice sticks across re-scans. Reset
// when the session changes.
const userToggled = ref(false)

// --- Ignore / dismiss findings (TASK-041 #7) --------------------------------
// Frontend-only, localStorage-persisted PER SESSION. A dismissed finding is hidden from
// the active list (and out of the header counts / auto-expand) but kept so the user can
// review + restore it. Finding ids are stable ("{code}:{column}"), so a dismissal sticks
// across re-scans and only a genuinely NEW issue (new id) resurfaces.
// Declared BEFORE the sessionUuid watch below — its immediate run reads these.
const ignoredIds = ref<Set<string>>(new Set())
const showIgnored = ref(false)
const IGNORE_PREFIX = 'spencer:quality-ignored:'

function loadIgnored(uuid: string): Set<string> {
  try {
    const raw = localStorage.getItem(IGNORE_PREFIX + uuid)
    const arr = raw ? JSON.parse(raw) : null
    return Array.isArray(arr) ? new Set(arr.filter((x): x is string => typeof x === 'string')) : new Set()
  } catch {
    return new Set()
  }
}
function persistIgnored(): void {
  const uuid = sessionUuid.value
  if (!uuid) return
  try {
    localStorage.setItem(IGNORE_PREFIX + uuid, JSON.stringify([...ignoredIds.value]))
  } catch {
    /* storage disabled/full — the in-memory set still holds for this session */
  }
}
function ignoreFinding(f: QualityFinding): void {
  const next = new Set(ignoredIds.value)
  next.add(f.id)
  ignoredIds.value = next
  persistIgnored()
}
function restoreFinding(f: QualityFinding): void {
  const next = new Set(ignoredIds.value)
  next.delete(f.id)
  ignoredIds.value = next
  persistIgnored()
}

// The report split by ignore state. `activeFindings` drives the list, header counts, and
// auto-expand; `ignoredFindings` backs the collapsible "ignored" section.
const activeFindings = computed<QualityFinding[]>(() =>
  report.value ? report.value.findings.filter((f) => !ignoredIds.value.has(f.id)) : [],
)
const ignoredFindings = computed<QualityFinding[]>(() =>
  report.value ? report.value.findings.filter((f) => ignoredIds.value.has(f.id)) : [],
)

// Monotonic guard: only the newest request may write state -- a dataVersion bump can
// kick off a fresh scan while an older one is still in flight.
let seq = 0
async function load(): Promise<void> {
  const uuid = sessionUuid.value
  if (!uuid) return
  const s = ++seq
  loading.value = true
  error.value = null
  try {
    const res = await fetchQualityReport(uuid, tableName.value ?? undefined)
    if (s !== seq) return
    report.value = res
    if (!userToggled.value) {
      // Auto-expand only for a NON-ignored high/medium issue — a dismissed one shouldn't
      // keep re-opening the card on every re-scan.
      expanded.value = res.findings.some(
        (f) => !ignoredIds.value.has(f.id) && (f.severity === 'high' || f.severity === 'medium'),
      )
    }
  } catch (e) {
    if (s !== seq) return
    report.value = null
    error.value = apiErrorMessage(e)
  } finally {
    if (s === seq) loading.value = false
  }
}

watch(
  sessionUuid,
  (uuid) => {
    // New (or cleared) session: drop stale state and the manual-toggle memory.
    report.value = null
    error.value = null
    userToggled.value = false
    expanded.value = false
    // TASK-041 #7: the ignored set is per-session — reload it for the new session.
    ignoredIds.value = uuid ? loadIgnored(uuid) : new Set()
    showIgnored.value = false
    if (uuid) void load()
    else seq++ // invalidate any in-flight response
  },
  { immediate: true },
)
// Re-scan after any transform/undo/redo (rows or schema changed).
watch(dataVersion, () => {
  if (sessionUuid.value) void load()
})

function toggle(): void {
  userToggled.value = true
  expanded.value = !expanded.value
}

// --- display helpers --------------------------------------------------------
const SEV_ORDER: QualitySeverity[] = ['high', 'medium', 'low', 'info']

// Solid design tokens only (opacity modifiers on the oklch CSS-var tokens are dropped
// by this Tailwind build): the coloured dot is the primary severity cue, the pill tint
// is secondary. high -> red, medium -> amber text, low -> gray, info -> primary.
const SEV_CHIP: Record<QualitySeverity, string> = {
  high: 'bg-surface-red text-ink-red border border-outline-red',
  medium: 'bg-surface-gray-1 text-ink-amber border border-outline-gray-2',
  low: 'bg-surface-gray-2 text-ink-gray-6 border border-outline-gray-2',
  info: 'bg-primary-1 text-primary-6 border border-primary-3',
}
const SEV_DOT: Record<QualitySeverity, string> = {
  high: 'bg-ink-red',
  medium: 'bg-ink-amber',
  low: 'bg-ink-gray-4',
  info: 'bg-primary',
}
const SEV_LABEL: Record<QualitySeverity, string> = {
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  info: 'Info',
}

// A short verb label for the Fix button, per suggested OpKind (only the ops the scan
// actually suggests need an entry; anything else falls back to "Fix").
const OP_LABEL: Record<string, string> = {
  drop_column: 'Drop column',
  impute_null: 'Fill nulls',
  cast: 'Cast type',
  string_normalize: 'Normalize text',
  dedupe: 'Remove duplicates',
  filter_rows: 'Filter rows',
  absolute_value: 'Make positive',
}

// Per-severity counts for the header summary, in severity order, nonzero only.
const counts = computed<{ severity: QualitySeverity; n: number }[]>(() => {
  const by = new Map<QualitySeverity, number>()
  for (const f of activeFindings.value) by.set(f.severity, (by.get(f.severity) ?? 0) + 1)
  return SEV_ORDER.flatMap((s) => {
    const n = by.get(s) ?? 0
    return n ? [{ severity: s, n }] : []
  })
})

const total = computed(() => activeFindings.value.length)

// Header alert-icon tone = the highest severity present (counts is already sorted).
const headerTone = computed(() => {
  const top = counts.value[0]
  if (!top) return 'text-ink-gray-4'
  if (top.severity === 'high') return 'text-ink-red'
  if (top.severity === 'medium') return 'text-ink-amber'
  return 'text-ink-gray-5'
})

function fmtInt(n: number): string {
  return n.toLocaleString()
}
function fixLabel(f: QualityFinding): string {
  return (f.suggested_op && OP_LABEL[f.suggested_op]) || 'Fix'
}
function onFix(f: QualityFinding): void {
  if (!f.suggested_op) return
  const req: OpRequest = { op: f.suggested_op, column: f.column ?? undefined }
  // text-as-date / text-as-number map to a cast. Pre-seed a COERCING cast to the right
  // type so the sentinel that triggered the finding is nulled in one step, with the
  // dry-run preview reporting exactly how many values that affects (TASK-017).
  if (f.code === 'text_as_date') {
    req.coerce = true
    req.newType = 'DATE'
  } else if (f.code === 'text_as_number') {
    req.coerce = true
    req.newType = 'DOUBLE'
  }
  // TASK-041 #2/#3/#6: newer findings ship a pre-filled param bundle (mixed values →
  // coercing cast, casing/punctuation variants → normalize, negatives → keep ≥ 0). Pass
  // it through as `seed` so the dialog opens ready to apply (dry-run preview still gates).
  if (f.suggested_params) req.seed = f.suggested_params
  emit('fix', req)
}
function onProfile(f: QualityFinding): void {
  if (f.column) emit('profile', f.column)
}

// TASK-042: some findings carry a SECOND remedy (`alt_op`/`alt_params`) — e.g. negative
// values can be dropped (keep ≥ 0) OR made positive (abs, keeps every row). When present
// it renders a second Fix button; the wiring mirrors onFix/fixLabel exactly.
function altLabel(f: QualityFinding): string {
  return (f.alt_op && OP_LABEL[f.alt_op]) || 'Fix'
}
function onFixAlt(f: QualityFinding): void {
  if (!f.alt_op) return
  const req: OpRequest = { op: f.alt_op, column: f.column ?? undefined }
  if (f.alt_params) req.seed = f.alt_params
  emit('fix', req)
}
</script>

<template>
  <section class="rounded-md border border-outline-gray-1 bg-surface-base shadow-sm">
    <!-- Header: click to expand/collapse. Always carries a one-line status summary. -->
    <button
      type="button"
      class="flex w-full items-center gap-3 px-3 py-2.5 text-left"
      :aria-expanded="expanded"
      @click="toggle"
    >
      <span class="shrink-0">
        <Loader2 v-if="loading" class="h-4 w-4 animate-spin text-ink-gray-4" />
        <AlertCircle v-else-if="error" class="h-4 w-4 text-ink-red" />
        <ShieldCheck v-else-if="report && total === 0" class="h-4 w-4 text-ink-green" />
        <ShieldAlert v-else-if="report" class="h-4 w-4" :class="headerTone" />
        <ShieldCheck v-else class="h-4 w-4 text-ink-gray-4" />
      </span>

      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span class="text-sm font-semibold text-ink-gray-8">Data quality</span>
          <span
            v-for="c in counts"
            :key="c.severity"
            class="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium"
            :class="SEV_CHIP[c.severity]"
          >
            <span class="h-1.5 w-1.5 rounded-full" :class="SEV_DOT[c.severity]"></span>
            {{ c.n }} {{ SEV_LABEL[c.severity].toLowerCase() }}
          </span>
        </div>
        <p class="mt-0.5 truncate text-xs" :class="error && !loading ? 'text-ink-red' : 'text-ink-gray-4'">
          <template v-if="loading">{{ report ? 'Re-scanning the table…' : 'Scanning the table…' }}</template>
          <template v-else-if="error">{{ error }}</template>
          <template v-else-if="report && total === 0">
            <template v-if="ignoredFindings.length">No active issues — {{ ignoredFindings.length }} ignored.</template>
            <template v-else>No issues detected across {{ fmtInt(report.column_count) }} columns · {{ fmtInt(report.row_count) }} rows.</template>
          </template>
          <template v-else-if="report">
            {{ total }} issue{{ total === 1 ? '' : 's' }} across {{ fmtInt(report.column_count) }} columns · {{ fmtInt(report.row_count) }} rows.
          </template>
          <template v-else>—</template>
        </p>
      </div>

      <component :is="expanded ? ChevronDown : ChevronRight" class="h-4 w-4 shrink-0 text-ink-gray-4" />
    </button>

    <!-- Body -->
    <div v-show="expanded" class="border-t border-outline-gray-1 px-3 py-3">
      <!-- A transform kicked off a fresh scan: flag the list below as stale + updating so a
           resolved finding that lingers for the scan's duration never reads as "the fix
           didn't work". Dim the stale content and show a re-scanning line above it. -->
      <div v-if="loading && report" class="mb-2 flex items-center gap-2 text-xs font-medium text-ink-gray-5">
        <Loader2 class="h-3.5 w-3.5 animate-spin" /> Re-scanning after your change…
      </div>
      <div :class="loading && report ? 'opacity-40 transition-opacity' : 'transition-opacity'">
      <!-- First scan in flight (no prior report to keep showing) -->
      <div v-if="loading && !report" class="flex items-center gap-2 py-4 text-sm text-ink-gray-4">
        <Loader2 class="h-4 w-4 animate-spin" /> Scanning…
      </div>

      <!-- Error (e.g. table dropped) -->
      <div
        v-else-if="error"
        class="flex items-start gap-2 rounded-3 border border-outline-gray-2 bg-surface-gray-1 p-3 text-sm text-ink-red"
      >
        <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
        <span>{{ error }}</span>
      </div>

      <!-- Clean table (no findings) OR every finding dismissed -->
      <div
        v-else-if="report && total === 0"
        class="flex items-center gap-2 rounded-3 border border-outline-gray-1 bg-surface-gray-1 p-3 text-sm text-ink-green"
      >
        <ShieldCheck class="h-4 w-4 shrink-0" />
        <span v-if="ignoredFindings.length">No active issues — {{ ignoredFindings.length }} finding{{ ignoredFindings.length === 1 ? '' : 's' }} ignored (shown below).</span>
        <span v-else>No quality issues detected — the table looks clean.</span>
      </div>

      <!-- Findings -->
      <div v-else-if="report" class="space-y-2">
        <div
          v-for="f in activeFindings"
          :key="f.id"
          class="flex items-start gap-3 rounded-3 border border-outline-gray-1 bg-surface-gray-1 p-3"
        >
          <span
            class="mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium"
            :class="SEV_CHIP[f.severity]"
          >
            <span class="h-1.5 w-1.5 rounded-full" :class="SEV_DOT[f.severity]"></span>
            {{ SEV_LABEL[f.severity] }}
          </span>

          <div class="min-w-0 flex-1">
            <p class="text-sm font-medium text-ink-gray-8">{{ f.title }}</p>
            <p class="mt-0.5 text-xs leading-relaxed text-ink-gray-5">{{ f.detail }}</p>
            <button
              v-if="f.column"
              type="button"
              class="mt-1 inline-flex items-center text-[11px] font-medium text-primary-6 hover:underline"
              :title="`Profile this column`"
              @click="onProfile(f)"
            >
              {{ f.column }}
            </button>
          </div>

          <div class="mt-0.5 flex shrink-0 items-center gap-1.5">
            <button
              v-if="f.suggested_op"
              type="button"
              class="btn btn-ghost shrink-0"
              :title="`Fix: ${fixLabel(f)}`"
              @click="onFix(f)"
            >
              <Wrench class="h-3.5 w-3.5" />
              {{ fixLabel(f) }}
            </button>
            <button
              v-if="f.alt_op"
              type="button"
              class="btn btn-ghost shrink-0"
              :title="`Fix: ${altLabel(f)}`"
              @click="onFixAlt(f)"
            >
              <Wrench class="h-3.5 w-3.5" />
              {{ altLabel(f) }}
            </button>
            <button
              type="button"
              class="inline-flex shrink-0 items-center gap-1 rounded-3 border border-outline-gray-2 bg-surface-base px-2 py-1 text-xs font-medium text-ink-gray-5 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-7"
              title="Ignore — hide this issue (restore it from the list below)"
              @click="ignoreFinding(f)"
            >
              <EyeOff class="h-3.5 w-3.5" />
              Ignore
            </button>
          </div>
        </div>

        <!-- Transparency: the compiled DuckDB SQL behind the scan (ADR-012). -->
        <details class="rounded-3 border border-outline-gray-1 bg-surface-gray-1">
          <summary class="cursor-pointer px-3 py-2 text-xs font-medium text-ink-gray-6">Compiled SQL</summary>
          <pre class="overflow-auto border-t border-outline-gray-1 px-3 py-2 text-[11px] leading-relaxed text-ink-gray-7">{{ report.compiled_sql }}</pre>
        </details>
      </div>

      <!-- Ignored findings (TASK-041 #7): a sibling OUTSIDE the v-if/else-if chain so it
           shows in both the clean and findings states. Collapsed by default. -->
      <div v-if="ignoredFindings.length" class="mt-3 border-t border-outline-gray-1 pt-3">
        <button
          type="button"
          class="inline-flex items-center gap-1.5 text-xs font-medium text-ink-gray-5 transition-colors hover:text-ink-gray-7"
          :aria-expanded="showIgnored"
          @click="showIgnored = !showIgnored"
        >
          <component :is="showIgnored ? Eye : EyeOff" class="h-3.5 w-3.5" />
          {{ showIgnored ? 'Hide' : 'Show' }} {{ ignoredFindings.length }} ignored issue{{ ignoredFindings.length === 1 ? '' : 's' }}
          <component :is="showIgnored ? ChevronDown : ChevronRight" class="h-3.5 w-3.5" />
        </button>
        <div v-if="showIgnored" class="mt-2 space-y-2">
          <div
            v-for="f in ignoredFindings"
            :key="f.id"
            class="flex items-start gap-3 rounded-3 border border-outline-gray-1 bg-surface-base p-3 opacity-75"
          >
            <span
              class="mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium"
              :class="SEV_CHIP[f.severity]"
            >
              <span class="h-1.5 w-1.5 rounded-full" :class="SEV_DOT[f.severity]"></span>
              {{ SEV_LABEL[f.severity] }}
            </span>
            <div class="min-w-0 flex-1">
              <p class="text-sm font-medium text-ink-gray-7">{{ f.title }}</p>
              <p class="mt-0.5 text-xs leading-relaxed text-ink-gray-4">{{ f.detail }}</p>
            </div>
            <button
              type="button"
              class="mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-3 border border-outline-gray-2 bg-surface-base px-2 py-1 text-xs font-medium text-ink-gray-6 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-8"
              title="Restore — move this issue back to the active list"
              @click="restoreFinding(f)"
            >
              <RotateCcw class="h-3.5 w-3.5" />
              Restore
            </button>
          </div>
        </div>
      </div>
      </div>
    </div>
  </section>
</template>
