<script setup lang="ts">
// One modal that drives all 10 cleaning ops. Given an OpRequest ({ op, column? })
// it renders just that op's fields, live-runs POST /transform/preview (a dry run —
// no version bump) to show the row-count delta + compiled SQL, then applies via the
// shared useSession().applyOp. Closed by emitting `close`.
import { reactive, ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { X, Play, Loader2, AlertCircle, Sparkles } from '@lucide/vue'
import { useSession } from '../composables/useSession'
import { previewTransform, apiErrorMessage, fetchColumnValues, askQuestion } from '../services/api'
import type {
  OpRequest,
  OpKind,
  TransformOp,
  TransformPreviewResponse,
  ImputeStrategy,
  ImputeNullOp,
  StringNormalizeOp,
  DedupeKeep,
  StringCase,
  FilterAction,
  SplitMode,
  DateExtractMode,
  DatePart,
  BinMethod,
  PadSide,
  FillDirection,
  OutlierMethod,
} from '../types'

const props = defineProps<{ request: OpRequest | null }>()
const emit = defineEmits<{ close: [] }>()

const { columns, sessionUuid, tableName, applyOp, applying, error } = useSession()

const OP_META: Record<OpKind, { title: string; desc: string }> = {
  dedupe: { title: 'Remove duplicate rows', desc: 'Delete rows that are exact duplicates across every column.' },
  drop_null: { title: 'Drop rows with nulls', desc: 'Remove rows where the chosen column is empty / null.' },
  impute_null: { title: 'Fill null values', desc: 'Replace nulls in a column with a computed or fixed value.' },
  cast: { title: 'Change column type', desc: 'Cast a column to a different data type.' },
  calculated_column: { title: 'Add calculated column', desc: 'Create a new column from a SQL expression over existing columns.' },
  drop_column: { title: 'Drop column', desc: 'Remove a column from the table.' },
  rename_column: { title: 'Rename column', desc: 'Give a column a new name.' },
  dedupe_subset: { title: 'Deduplicate by key columns', desc: 'Keep the first or last row within each group of the key columns.' },
  string_normalize: { title: 'Normalize text', desc: 'Trim, change case, regex/plain find-replace, strip special chars, pad, or blank out tokens.' },
  split_column: { title: 'Split / extract into new column', desc: 'Derive a new column: take a delimited field, or a regex capture group, from a text column.' },
  date_extract: { title: 'Date parts / reformat', desc: 'Derive a new column: extract Y/M/D/quarter/weekday (hour/min/sec need a timestamp), or reformat via strftime.' },
  bin_column: { title: 'Bin into ranges', desc: 'Bucket a numeric column into a new 0-based bin index — equal-width ranges or equal-count quantiles.' },
  fill_down: { title: 'Fill down / up', desc: 'Fill nulls in a column with the last (down) or next (up) non-null value in row order.' },
  flag_outliers: { title: 'Flag outliers', desc: 'Add a boolean column marking rows more than N standard deviations from the column mean (z-score).' },
  filter_rows: { title: 'Filter rows', desc: 'Keep or remove rows matching a SQL predicate.' },
  // In-cell edits (TASK-041 #5) are applied straight from the grid, not this dialog; the
  // entry only exists to keep this map exhaustive over OpKind.
  update_cell: { title: 'Edit cell', desc: 'Set a single cell to a new value.' },
  absolute_value: { title: 'Make values positive', desc: 'Replace a numeric column with its absolute value — drops the negative sign, keeps every row.' },
}

const CAST_TYPES = ['VARCHAR', 'BIGINT', 'DOUBLE', 'BOOLEAN', 'DATE', 'TIMESTAMP']
const STRATEGIES: { value: ImputeStrategy; label: string }[] = [
  { value: 'mean', label: 'Mean' },
  { value: 'median', label: 'Median' },
  { value: 'mode', label: 'Most frequent' },
  { value: 'zero', label: 'Zero / empty' },
  { value: 'custom', label: 'Custom value…' },
]

// One flat form; only the fields the active op reads are ever sent (see buildOp).

// AI Formula Generator State
const showAIPrompt = ref(false)
const aiPrompt = ref('')
const isGenerating = ref(false)
const aiError = ref<string | null>(null)

async function generateFormula() {
  if (!aiPrompt.value.trim() || !sessionUuid.value) return
  isGenerating.value = true
  aiError.value = null
  try {
    const prompt = `Write a valid DuckDB SQL SELECT query that computes: '${aiPrompt.value}'. 
CRITICAL RULES:
1. This is a ROW-LEVEL scalar calculation. DO NOT use aggregate functions like SUM, COUNT, AVG, MAX, MIN. They are STRICTLY BANNED and will cause a syntax crash.
2. Use ONLY scalar arithmetic (+, -, *, /) and basic scalar functions (e.g., COALESCE, UPPER, ROUND, CAST).
3. You MUST return a full SELECT statement selecting EXACTLY ONE column.
4. You MUST alias the column with a short, descriptive name using AS (do NOT put quotes around the alias).
5. You MUST include a FROM clause with a dummy table name like 't'.
6. Do NOT include markdown blocks (\`\`\`sql) or any conversational text.
Example: SELECT (manufacturing_cost + freight_cost) * Qty AS Total_Cost FROM t`
    
    const res = await askQuestion(sessionUuid.value, prompt)
    
    let sql = res.sql.replace(/;/g, '').trim()
    // Strip markdown formatting if any
    sql = sql.replace(/^```sql/i, '').replace(/```$/i, '').trim()
    
    // Parse: SELECT <expression> AS <name> FROM <table>
    const match = sql.match(/^SELECT\s+([\s\S]+?)\s+AS\s+["']?([a-zA-Z0-9_ ]+)["']?\s+FROM\s+/i)
    
    if (match) {
      form.formula = match[1].trim()
      // Always overwrite the new column name with the AI's suggestion
      form.newColumnName = match[2].trim().replace(/\s+/g, '_')
    } else {
      // Fallback if the regex fails
      let fallback = sql.replace(/^SELECT\s+/i, '').replace(/\s+FROM\s+.*$/i, '').trim()
      const fallbackMatch = fallback.match(/^([\s\S]+?)\s+AS\s+["']?([a-zA-Z0-9_ ]+)["']?$/i)
      if (fallbackMatch) {
        form.formula = fallbackMatch[1].trim()
        form.newColumnName = fallbackMatch[2].trim().replace(/\s+/g, '_')
      } else {
        form.formula = fallback
      }
    }
    showAIPrompt.value = false
  } catch (e) {
    console.error('Failed to generate formula', e)
    aiError.value = e instanceof Error ? e.message : String(e)
  } finally {
    isGenerating.value = false
  }
}

const form = reactive({
  column: '',
  columns: [] as string[],
  strategy: 'mean' as ImputeStrategy,
  fillValue: '',
  newType: 'VARCHAR',
  coerce: false,
  newColumnName: '',
  formula: '',
  newName: '',
  keep: 'first' as DedupeKeep,
  trim: false,
  scase: '' as '' | StringCase,
  find: '',
  replace: '',
  nullToken: '',
  predicate: '',
  action: 'keep' as FilterAction,
  // --- TASK-018 text-toolkit extensions (string_normalize) ---
  regex: false,
  stripSpecial: false,
  padSide: '' as '' | PadSide,
  padLength: 10,
  padChar: '',
  // --- TASK-018 split_column ---
  splitMode: 'delimiter' as SplitMode,
  delimiter: '',
  splitIndex: 0,
  pattern: '',
  group: 0,
  // --- TASK-018 date_extract ---
  dateMode: 'part' as DateExtractMode,
  datePart: 'year' as DatePart,
  dateFormat: '',
  // --- TASK-018 bin_column ---
  binMethod: 'equal_width' as BinMethod,
  bins: 5,
  // --- TASK-019 fill_down / flag_outliers ---
  fillDirection: 'down' as FillDirection,
  outlierMethod: 'zscore' as OutlierMethod,
  threshold: 3,
  // --- TASK-041 (#4 impute decimals, #3/#6 collapse internal whitespace) ---
  collapseWhitespace: false,
  roundEnabled: false,
  decimals: 2,
})

const preview = ref<TransformPreviewResponse | null>(null)
const previewing = ref(false)
const previewError = ref<string | null>(null)
const applyError = ref<string | null>(null)

// TASK-042: distinct values of the normalize column, offered as a <datalist> dropdown on
// the Find field so a value can be picked instead of retyped. Populated lazily (only for
// string_normalize) via GET /column/values; `findTruncated` flags a high-cardinality
// column whose list was capped server-side (the field still accepts free text).
const findValues = ref<string[]>([])
const findTruncated = ref(false)
let findSeq = 0
async function loadFindValues(): Promise<void> {
  findValues.value = []
  findTruncated.value = false
  if (!props.request || props.request.op !== 'string_normalize') return
  const uuid = sessionUuid.value
  const col = form.column.trim()
  if (!uuid || !col) return
  const seq = ++findSeq
  try {
    const res = await fetchColumnValues(uuid, col, tableName.value ?? undefined)
    if (seq !== findSeq) return // a newer load (column/op change) superseded this one
    findValues.value = res.values.filter((v) => v != null).map((v) => String(v))
    findTruncated.value = res.truncated
  } catch {
    // Non-fatal: the dropdown is a convenience; the Find field still works as free text.
    if (seq === findSeq) { findValues.value = []; findTruncated.value = false }
  }
}

const meta = computed(() => (props.request ? OP_META[props.request.op] : null))

// Assemble the typed TransformOp from the form, or an error string explaining what's
// still missing (drives the disabled-Apply hint). Exhaustive over OpKind.
function buildOp(): { op: TransformOp } | { error: string } {
  const r = props.request
  if (!r) return { error: 'No operation selected' }
  const col = form.column.trim()
  switch (r.op) {
    case 'dedupe':
      return { op: { op: 'dedupe' } }
    case 'drop_null':
      if (!col) return { error: 'Select a column' }
      return { op: { op: 'drop_null', column: col } }
    case 'drop_column':
      if (!col) return { error: 'Select a column' }
      return { op: { op: 'drop_column', column: col } }
    case 'impute_null': {
      if (!col) return { error: 'Select a column' }
      if (form.strategy === 'custom' && form.fillValue.trim() === '')
        return { error: 'Enter a fill value' }
      const op: ImputeNullOp = { op: 'impute_null', column: col, strategy: form.strategy }
      if (form.strategy === 'custom') op.fill_value = form.fillValue
      // TASK-041 #4: optionally round a computed mean/median fill (no effect on the other
      // strategies — a zero/mode/custom value isn't a long decimal).
      if ((form.strategy === 'mean' || form.strategy === 'median') && form.roundEnabled) {
        if (!Number.isInteger(form.decimals) || form.decimals < 0 || form.decimals > 10)
          return { error: 'Decimals must be a whole number from 0 to 10' }
        op.decimals = form.decimals
      }
      return { op }
    }
    case 'cast':
      if (!col) return { error: 'Select a column' }
      if (!form.newType) return { error: 'Choose a target type' }
      return { op: { op: 'cast', column: col, new_type: form.newType, coerce: form.coerce } }
    case 'rename_column': {
      if (!col) return { error: 'Select a column' }
      const nn = form.newName.trim()
      if (!nn) return { error: 'Enter a new name' }
      return { op: { op: 'rename_column', column: col, new_name: nn } }
    }
    case 'calculated_column': {
      const name = form.newColumnName.trim()
      const formula = form.formula.trim()
      if (!name) return { error: 'Enter a column name' }
      if (!formula) return { error: 'Enter a formula' }
      return { op: { op: 'calculated_column', new_column_name: name, formula } }
    }
    case 'dedupe_subset':
      if (form.columns.length === 0) return { error: 'Select at least one key column' }
      return { op: { op: 'dedupe_subset', columns: [...form.columns], keep: form.keep } }
    case 'filter_rows': {
      const pred = form.predicate.trim()
      if (!pred) return { error: 'Enter a predicate' }
      return { op: { op: 'filter_rows', predicate: pred, action: form.action } }
    }
    case 'string_normalize': {
      if (!col) return { error: 'Select a column' }
      const op: StringNormalizeOp = { op: 'string_normalize', column: col }
      let any = false
      if (form.trim) { op.trim = true; any = true }
      if (form.scase) { op.case = form.scase; any = true }
      if (form.stripSpecial) { op.strip_special = true; any = true }
      if (form.collapseWhitespace) { op.collapse_whitespace = true; any = true }
      if (form.find) {
        op.find = form.find
        op.replace = form.replace
        if (form.regex) op.regex = true
        any = true
      }
      if (form.padSide) {
        if (!Number.isInteger(form.padLength) || form.padLength <= 0)
          return { error: 'Pad length must be a positive whole number' }
        if (form.padChar.length > 1) return { error: 'Pad character must be a single character' }
        op.pad_side = form.padSide
        op.pad_length = form.padLength
        if (form.padChar) op.pad_char = form.padChar
        any = true
      }
      if (form.nullToken) { op.null_token = form.nullToken; any = true }
      if (!any) return { error: 'Choose at least one normalization' }
      return { op }
    }
    case 'split_column': {
      if (!col) return { error: 'Select a source column' }
      const name = form.newColumnName.trim()
      if (!name) return { error: 'Enter a new column name' }
      if (form.splitMode === 'delimiter') {
        if (!form.delimiter) return { error: 'Enter a delimiter' }
        if (!Number.isInteger(form.splitIndex) || form.splitIndex < 0)
          return { error: 'Field index must be 0 or greater' }
        return { op: { op: 'split_column', column: col, new_column_name: name, mode: 'delimiter', delimiter: form.delimiter, index: form.splitIndex } }
      }
      if (!form.pattern.trim()) return { error: 'Enter a regex pattern' }
      if (!Number.isInteger(form.group) || form.group < 0)
        return { error: 'Capture group must be 0 or greater' }
      return { op: { op: 'split_column', column: col, new_column_name: name, mode: 'regex', pattern: form.pattern, group: form.group } }
    }
    case 'date_extract': {
      if (!col) return { error: 'Select a source column' }
      const name = form.newColumnName.trim()
      if (!name) return { error: 'Enter a new column name' }
      if (form.dateMode === 'part') {
        return { op: { op: 'date_extract', column: col, new_column_name: name, mode: 'part', part: form.datePart } }
      }
      if (!form.dateFormat.trim()) return { error: 'Enter a format string' }
      return { op: { op: 'date_extract', column: col, new_column_name: name, mode: 'format', date_format: form.dateFormat } }
    }
    case 'bin_column': {
      if (!col) return { error: 'Select a source column' }
      const name = form.newColumnName.trim()
      if (!name) return { error: 'Enter a new column name' }
      if (!Number.isInteger(form.bins) || form.bins < 2 || form.bins > 50)
        return { error: 'Bins must be a whole number between 2 and 50' }
      return { op: { op: 'bin_column', column: col, new_column_name: name, method: form.binMethod, bins: form.bins } }
    }
    case 'fill_down':
      if (!col) return { error: 'Select a column' }
      return { op: { op: 'fill_down', column: col, direction: form.fillDirection } }
    case 'flag_outliers': {
      if (!col) return { error: 'Select a source column' }
      const name = form.newColumnName.trim()
      if (!name) return { error: 'Enter a new column name' }
      if (!Number.isFinite(form.threshold) || form.threshold <= 0)
        return { error: 'Threshold must be a positive number' }
      return { op: { op: 'flag_outliers', column: col, new_column_name: name, method: form.outlierMethod, threshold: form.threshold } }
    }
    case 'absolute_value':
      // TASK-042: no fields — abs() the chosen numeric column in place. The dry-run
      // preview shows the effect; Apply commits (undoable). Numeric-only (backend guard).
      if (!col) return { error: 'Select a column' }
      return { op: { op: 'absolute_value', column: col } }
    // update_cell is applied directly by the grid's in-cell editor (TASK-041 #5) and is
    // never opened through this dialog, so it has no form here.
    default:
      return { error: 'This operation is not available here' }
  }
}

const built = computed(() => buildOp())
const validationError = computed(() => ('error' in built.value ? built.value.error : null))
const delta = computed(() => preview.value?.row_count_delta ?? 0)

// Monotonic guard: only the newest preview response is allowed to land, so quickly
// editing fields (or reopening the dialog for another op) can't show a stale result.
let previewSeq = 0
async function runPreview(): Promise<void> {
  const b = built.value
  if (!('op' in b)) return
  const uuid = sessionUuid.value
  if (!uuid) return
  const seq = ++previewSeq
  previewing.value = true
  previewError.value = null
  try {
    const res = await previewTransform(uuid, b.op, tableName.value ?? undefined)
    if (seq === previewSeq) preview.value = res
  } catch (e) {
    if (seq === previewSeq) {
      preview.value = null
      previewError.value = apiErrorMessage(e)
    }
  } finally {
    if (seq === previewSeq) previewing.value = false
  }
}

// Debounced auto-preview: refresh whenever the assembled op changes and is valid.
let debounceTimer: ReturnType<typeof setTimeout> | null = null
watch(built, () => {
  if (!props.request) return
  if (debounceTimer) clearTimeout(debounceTimer)
  if ('error' in built.value) {
    preview.value = null
    previewSeq++ // cancel any in-flight preview; the op is no longer valid
    return
  }
  debounceTimer = setTimeout(() => void runPreview(), 350)
})

// Map a quality-panel Fix's `suggested_params` (snake_case op-field keys) onto the flat
// form so the dialog opens pre-filled and one Apply away. Only known keys with the right
// runtime type are applied — an unexpected shape is ignored, never trusted blindly.
function applySeed(seed: Record<string, unknown> | undefined): void {
  if (!seed) return
  if (typeof seed.coerce === 'boolean') form.coerce = seed.coerce
  if (typeof seed.new_type === 'string') form.newType = seed.new_type
  if (typeof seed.predicate === 'string') form.predicate = seed.predicate
  if (seed.action === 'keep' || seed.action === 'remove') form.action = seed.action
  if (seed.case === 'upper' || seed.case === 'lower' || seed.case === 'capitalize') form.scase = seed.case
  if (typeof seed.trim === 'boolean') form.trim = seed.trim
  if (typeof seed.strip_special === 'boolean') form.stripSpecial = seed.strip_special
  if (typeof seed.collapse_whitespace === 'boolean') form.collapseWhitespace = seed.collapse_whitespace
  if (
    seed.strategy === 'mean' || seed.strategy === 'median' || seed.strategy === 'mode' ||
    seed.strategy === 'zero' || seed.strategy === 'custom'
  ) form.strategy = seed.strategy
  if (typeof seed.decimals === 'number') { form.decimals = seed.decimals; form.roundEnabled = true }
  if (seed.fill_value != null) form.fillValue = String(seed.fill_value)
}

// Reset the form to op-appropriate defaults each time a new request opens.
watch(
  () => props.request,
  (r) => {
    preview.value = null
    previewError.value = null
    applyError.value = null
    previewSeq++ // invalidate any preview still in flight from the previous request
    if (!r) return
    form.column = r.column ?? (columns.value[0]?.name ?? '')
    form.columns = []
    form.strategy = 'mean'
    form.fillValue = ''
    form.newType = r.newType ?? 'VARCHAR'
    form.coerce = r.coerce ?? false
    form.newColumnName = ''
    form.formula = ''
    form.newName = ''
    form.keep = 'first'
    form.trim = false
    form.scase = ''
    form.find = ''
    form.replace = ''
    form.nullToken = ''
    form.predicate = ''
    form.action = 'keep'
    // TASK-018 text-toolkit extensions
    form.regex = false
    form.stripSpecial = false
    form.padSide = ''
    form.padLength = 10
    form.padChar = ''
    // TASK-018 split_column
    form.splitMode = 'delimiter'
    form.delimiter = ''
    form.splitIndex = 0
    form.pattern = ''
    form.group = 0
    // TASK-018 date_extract
    form.dateMode = 'part'
    form.datePart = 'year'
    form.dateFormat = ''
    // TASK-018 bin_column
    form.binMethod = 'equal_width'
    form.bins = 5
    // TASK-019 fill_down / flag_outliers
    form.fillDirection = 'down'
    form.outlierMethod = 'zscore'
    form.threshold = 3
    // TASK-041 (#4 impute decimals, #3/#6 collapse whitespace)
    form.collapseWhitespace = false
    form.roundEnabled = false
    form.decimals = 2
    // Overlay any Fix-provided seed AFTER the defaults above (may override newType/coerce
    // for a coercing cast, predicate/action for a filter, case/strip/collapse for a
    // normalize, etc.), so a one-click Fix lands on the dialog ready to apply.
    applySeed(r.seed)
    // TASK-042: prime the Find dropdown for a normalize op (no-op for every other op).
    void loadFindValues()
  },
  { immediate: true },
)

// Reload the Find dropdown when the user switches the normalize column mid-dialog.
watch(
  () => form.column,
  () => { if (props.request?.op === 'string_normalize') void loadFindValues() },
)

async function apply(): Promise<void> {
  const b = built.value
  if (!('op' in b)) return
  applyError.value = null
  const ok = await applyOp(b.op)
  if (ok) emit('close')
  else applyError.value = error.value // applyOp surfaced the failure on the shared state
}

function close(): void {
  emit('close')
}

function toggleKeyColumn(name: string): void {
  const i = form.columns.indexOf(name)
  if (i === -1) form.columns.push(name)
  else form.columns.splice(i, 1)
}

// Escape closes the dialog whenever it's open.
function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape' && props.request) close()
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

const inputCls =
  'w-full rounded-3 border border-outline-gray-2 bg-surface-base px-3 py-1.5 text-sm text-ink-gray-9 focus:border-primary-5 focus:outline-none'
const labelCls = 'block text-xs font-medium text-ink-gray-7 mb-1'
</script>

<template>
  <div
    v-if="request && meta"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    @click.self="close"
  >
    <div class="flex max-h-[88vh] w-full max-w-lg flex-col overflow-hidden rounded-5 border border-outline-gray-1 bg-surface-base shadow-lg">
      <!-- Header -->
      <div class="flex items-start justify-between border-b border-outline-gray-1 px-5 py-4">
        <div>
          <h3 class="text-sm font-semibold text-ink-gray-9">{{ meta.title }}</h3>
          <p class="mt-0.5 text-xs text-ink-gray-5">{{ meta.desc }}</p>
        </div>
        <button
          type="button"
          class="ml-3 shrink-0 rounded-3 p-1 text-ink-gray-5 hover:bg-surface-gray-2 hover:text-ink-gray-8"
          title="Close"
          @click="close"
        >
          <X class="h-4 w-4" />
        </button>
      </div>

      <!-- Body -->
      <div class="flex-1 space-y-4 overflow-y-auto px-5 py-4">
        <!-- Column picker (shared by the column-scoped ops) -->
        <div
          v-if="['drop_null', 'impute_null', 'cast', 'drop_column', 'rename_column', 'string_normalize', 'split_column', 'date_extract', 'bin_column', 'fill_down', 'flag_outliers', 'absolute_value'].includes(request.op)"
        >
          <label class="block text-xs font-medium text-ink-gray-7 mb-1">{{ ['split_column', 'date_extract', 'bin_column', 'flag_outliers'].includes(request.op) ? 'Source column' : 'Column' }}</label>
          <select v-model="form.column" :class="inputCls">
            <option v-for="c in columns" :key="c.name" :value="c.name">{{ c.name }} · {{ c.type }}</option>
          </select>
        </div>

        <!-- New column name (the derive ops add a column) -->
        <div v-if="['split_column', 'date_extract', 'bin_column', 'flag_outliers'].includes(request.op)">
          <label :class="labelCls">New column name</label>
          <input v-model="form.newColumnName" type="text" :class="inputCls" placeholder="new_column" />
        </div>

        <!-- impute_null -->
        <template v-if="request.op === 'impute_null'">
          <div>
            <label :class="labelCls">Strategy</label>
            <select v-model="form.strategy" :class="inputCls">
              <option v-for="s in STRATEGIES" :key="s.value" :value="s.value">{{ s.label }}</option>
            </select>
          </div>
          <div v-if="form.strategy === 'custom'">
            <label :class="labelCls">Fill value</label>
            <input v-model="form.fillValue" type="text" :class="inputCls" placeholder="e.g. 0 or Unknown" />
          </div>
          <!-- TASK-041 #4: optional rounding for a computed mean/median fill -->
          <div v-if="form.strategy === 'mean' || form.strategy === 'median'">
            <label class="flex items-center gap-2 text-sm text-ink-gray-8">
              <input type="checkbox" v-model="form.roundEnabled" />
              Round to
              <input
                v-model.number="form.decimals"
                type="number"
                min="0"
                max="10"
                :disabled="!form.roundEnabled"
                class="w-16 rounded-3 border border-outline-gray-2 bg-surface-base px-2 py-1 text-sm text-ink-gray-9 focus:border-primary-5 focus:outline-none disabled:opacity-50"
              />
              decimal places
            </label>
            <p class="mt-1 text-[11px] text-ink-gray-4">The mean/median is often a long decimal; round it to keep the column tidy.</p>
          </div>
        </template>

        <!-- cast -->
        <div v-if="request.op === 'cast'" class="space-y-2">
          <div>
            <label :class="labelCls">New type</label>
            <select v-model="form.newType" :class="inputCls">
              <option v-for="t in CAST_TYPES" :key="t" :value="t">{{ t }}</option>
            </select>
          </div>
          <label class="flex items-center gap-2 text-sm text-ink-gray-8">
            <input type="checkbox" v-model="form.coerce" />
            Coerce: set values that can't convert to <span class="font-medium">{{ form.newType }}</span> to NULL
          </label>
          <p class="text-[11px] text-ink-gray-4">
            Off, a single un-convertible value fails the whole cast. On, only those values become NULL — the preview shows how many.
          </p>
        </div>

        <!-- rename_column -->
        <div v-if="request.op === 'rename_column'">
          <label :class="labelCls">New name</label>
          <input v-model="form.newName" type="text" :class="inputCls" placeholder="new_column_name" />
        </div>

        <!-- calculated_column -->
        <template v-if="request.op === 'calculated_column'">
          <div>
            <label :class="labelCls">New column name</label>
            <input v-model="form.newColumnName" type="text" :class="inputCls" placeholder="total_price" />
          </div>
          <div>
            <div class="flex items-center justify-between mb-1">
              <label :class="labelCls" style="margin-bottom: 0;">Formula (SQL expression)</label>
              <button type="button" @click="showAIPrompt = !showAIPrompt" class="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-primary hover:text-primary-6 transition-colors focus:outline-none">
                <Sparkles class="h-3 w-3" />
                Ask AI
              </button>
            </div>
            
            <div v-if="showAIPrompt" class="mb-2 flex items-center gap-1.5 rounded-3 border border-primary-3 bg-primary-1 p-1 shadow-inner transition-all">
              <input v-model="aiPrompt" type="text" class="min-w-0 flex-1 rounded-2 border-none bg-transparent px-2 py-1 text-xs font-medium text-ink-gray-8 placeholder-ink-gray-4 focus:ring-0 focus:outline-none" placeholder="e.g. Extract the year from birthdate..." @keydown.enter.prevent="generateFormula" />
              <button type="button" @click="generateFormula" :disabled="isGenerating || !aiPrompt.trim()" class="shrink-0 rounded-2 bg-primary px-3 py-1.5 text-[11px] font-bold text-white shadow-sm transition-colors hover:bg-primary-6 disabled:opacity-50">
                <Loader2 v-if="isGenerating" class="h-3.5 w-3.5 animate-spin" />
                <span v-else>Generate</span>
              </button>
            </div>
            <div v-if="aiError" class="mb-2 text-xs font-semibold text-ink-red">
              {{ aiError }}
            </div>

            <input v-model="form.formula" type="text" :class="inputCls" placeholder="quantity * unit_price" />
            <p class="mt-1 text-[11px] text-ink-gray-4">Reference existing columns by name, e.g. <code>price * 1.1</code>.</p>
          </div>
        </template>

        <!-- dedupe_subset -->
        <template v-if="request.op === 'dedupe_subset'">
          <div>
            <label :class="labelCls">Key columns</label>
            <div class="max-h-40 space-y-1 overflow-y-auto rounded-3 border border-outline-gray-2 p-2">
              <label
                v-for="c in columns"
                :key="c.name"
                class="flex cursor-pointer items-center gap-2 rounded-2 px-2 py-1 text-sm text-ink-gray-8 hover:bg-surface-gray-2"
              >
                <input
                  type="checkbox"
                  :checked="form.columns.includes(c.name)"
                  @change="toggleKeyColumn(c.name)"
                />
                <span class="truncate">{{ c.name }}</span>
                <span class="ml-auto text-[11px] uppercase text-ink-gray-4">{{ c.type }}</span>
              </label>
            </div>
          </div>
          <div>
            <label :class="labelCls">Keep</label>
            <select v-model="form.keep" :class="inputCls">
              <option value="first">First row in each group</option>
              <option value="last">Last row in each group</option>
            </select>
          </div>
        </template>

        <!-- string_normalize -->
        <template v-if="request.op === 'string_normalize'">
          <label class="flex items-center gap-2 text-sm text-ink-gray-8">
            <input type="checkbox" v-model="form.trim" /> Trim leading / trailing whitespace
          </label>
          <label class="flex items-center gap-2 text-sm text-ink-gray-8">
            <input type="checkbox" v-model="form.stripSpecial" /> Strip special characters (keep letters, digits, spaces)
          </label>
          <label class="flex items-center gap-2 text-sm text-ink-gray-8">
            <input type="checkbox" v-model="form.collapseWhitespace" /> Collapse repeated spaces into one (and trim ends)
          </label>
          <div>
            <label :class="labelCls">Case</label>
            <select v-model="form.scase" :class="inputCls">
              <option value="">Leave unchanged</option>
              <option value="upper">UPPERCASE</option>
              <option value="lower">lowercase</option>
              <option value="capitalize">Capitalize</option>
            </select>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label :class="labelCls">Find</label>
              <!-- TASK-042: in plain (non-regex) mode, offer the column's distinct values as a
                   typeable dropdown (native <datalist>). Regex mode omits the list — the field
                   is a pattern then, not a literal value. -->
              <input
                v-model="form.find"
                type="text"
                :class="inputCls"
                :list="form.regex ? undefined : 'op-find-values'"
                :placeholder="form.regex ? 'regex, e.g. \\d+' : (findValues.length ? 'pick a value or type…' : 'text to find')"
              />
              <datalist v-if="!form.regex" id="op-find-values">
                <option v-for="v in findValues" :key="v" :value="v" />
              </datalist>
              <p v-if="!form.regex && findTruncated" class="mt-1 text-[11px] text-ink-gray-4">
                Showing the most common values only — this column has more than the list can hold.
              </p>
            </div>
            <div>
              <label :class="labelCls">Replace with</label>
              <input v-model="form.replace" type="text" :class="inputCls" placeholder="replacement" />
            </div>
          </div>
          <label class="flex items-center gap-2 text-sm text-ink-gray-8">
            <input type="checkbox" v-model="form.regex" /> Treat “Find” as a regular expression (global replace)
          </label>
          <div>
            <label :class="labelCls">Pad</label>
            <div class="grid grid-cols-3 gap-3">
              <select v-model="form.padSide" :class="inputCls">
                <option value="">No padding</option>
                <option value="left">Pad left</option>
                <option value="right">Pad right</option>
              </select>
              <input v-model.number="form.padLength" type="number" min="1" :class="inputCls" :disabled="!form.padSide" placeholder="length" />
              <input v-model="form.padChar" type="text" maxlength="1" :class="inputCls" :disabled="!form.padSide" placeholder="fill (space)" />
            </div>
          </div>
          <div>
            <label :class="labelCls">Treat token as null</label>
            <input v-model="form.nullToken" type="text" :class="inputCls" placeholder="e.g. N/A" />
          </div>
        </template>

        <!-- split_column -->
        <template v-if="request.op === 'split_column'">
          <div>
            <label :class="labelCls">Mode</label>
            <select v-model="form.splitMode" :class="inputCls">
              <option value="delimiter">Split on delimiter</option>
              <option value="regex">Regex capture group</option>
            </select>
          </div>
          <template v-if="form.splitMode === 'delimiter'">
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label :class="labelCls">Delimiter</label>
                <input v-model="form.delimiter" type="text" :class="inputCls" placeholder="e.g. - or ," />
              </div>
              <div>
                <label :class="labelCls">Field index (0-based)</label>
                <input v-model.number="form.splitIndex" type="number" min="0" :class="inputCls" />
              </div>
            </div>
            <p class="text-[11px] text-ink-gray-4">Takes the Nth field after splitting; out-of-range → NULL.</p>
          </template>
          <template v-else>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label :class="labelCls">Pattern (regex)</label>
                <input v-model="form.pattern" type="text" :class="inputCls" placeholder="([A-Za-z]+)" />
              </div>
              <div>
                <label :class="labelCls">Capture group</label>
                <input v-model.number="form.group" type="number" min="0" :class="inputCls" />
              </div>
            </div>
            <p class="text-[11px] text-ink-gray-4">Group 0 = whole match; 1+ = the Nth capture.</p>
          </template>
        </template>

        <!-- date_extract -->
        <template v-if="request.op === 'date_extract'">
          <div>
            <label :class="labelCls">Mode</label>
            <select v-model="form.dateMode" :class="inputCls">
              <option value="part">Extract a part</option>
              <option value="format">Reformat (strftime)</option>
            </select>
          </div>
          <div v-if="form.dateMode === 'part'">
            <label :class="labelCls">Part</label>
            <select v-model="form.datePart" :class="inputCls">
              <option value="year">Year</option>
              <option value="month">Month</option>
              <option value="day">Day</option>
              <option value="quarter">Quarter</option>
              <option value="dayofyear">Day of year</option>
              <option value="weekday">Weekday (0 = Mon)</option>
              <option value="weekday_name">Weekday name</option>
              <option value="hour">Hour (timestamp)</option>
              <option value="minute">Minute (timestamp)</option>
              <option value="second">Second (timestamp)</option>
            </select>
            <p class="mt-1 text-[11px] text-ink-gray-4">Hour / minute / second require a TIMESTAMP source column.</p>
          </div>
          <div v-else>
            <label :class="labelCls">Format string</label>
            <input v-model="form.dateFormat" type="text" :class="inputCls" placeholder="%Y-%m-%d" />
            <p class="mt-1 text-[11px] text-ink-gray-4">strftime tokens, e.g. <code>%Y-%m</code> → 2026-08.</p>
          </div>
        </template>

        <!-- bin_column -->
        <template v-if="request.op === 'bin_column'">
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label :class="labelCls">Method</label>
              <select v-model="form.binMethod" :class="inputCls">
                <option value="equal_width">Equal-width ranges</option>
                <option value="quantile">Quantiles (equal count)</option>
              </select>
            </div>
            <div>
              <label :class="labelCls">Number of bins (2–50)</label>
              <input v-model.number="form.bins" type="number" min="2" max="50" :class="inputCls" />
            </div>
          </div>
          <p class="text-[11px] text-ink-gray-4">Produces a 0-based bin index (0 … bins − 1).</p>
        </template>

        <!-- fill_down -->
        <template v-if="request.op === 'fill_down'">
          <div>
            <label :class="labelCls">Direction</label>
            <select v-model="form.fillDirection" :class="inputCls">
              <option value="down">Down — carry last value forward</option>
              <option value="up">Up — carry next value backward</option>
            </select>
            <p class="mt-1 text-[11px] text-ink-gray-4">Fills nulls in row order; leading/trailing nulls with no value to borrow stay null.</p>
          </div>
        </template>

        <!-- flag_outliers -->
        <template v-if="request.op === 'flag_outliers'">
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label :class="labelCls">Method</label>
              <select v-model="form.outlierMethod" :class="inputCls">
                <option value="zscore">Z-score (std devs from mean)</option>
              </select>
            </div>
            <div>
              <label :class="labelCls">Threshold (σ)</label>
              <input v-model.number="form.threshold" type="number" min="0" step="0.5" :class="inputCls" />
            </div>
          </div>
          <p class="text-[11px] text-ink-gray-4">Adds a boolean column: true where |value − mean| &gt; threshold × std.</p>
        </template>

        <!-- filter_rows -->
        <template v-if="request.op === 'filter_rows'">
          <div>
            <label :class="labelCls">Predicate (SQL)</label>
            <input v-model="form.predicate" type="text" :class="inputCls" placeholder="amount > 100 AND status = 'paid'" />
          </div>
          <div>
            <label :class="labelCls">Action</label>
            <select v-model="form.action" :class="inputCls">
              <option value="keep">Keep matching rows</option>
              <option value="remove">Remove matching rows</option>
            </select>
          </div>
        </template>

        <!-- dedupe has no fields -->
        <p v-if="request.op === 'dedupe'" class="text-sm text-ink-gray-6">
          This removes rows that are exact duplicates across all columns. Preview the impact below.
        </p>

        <!-- absolute_value has no fields beyond the column picker (TASK-042) -->
        <p v-if="request.op === 'absolute_value'" class="text-sm text-ink-gray-6">
          Replaces every value in the chosen column with its absolute value — the negative sign is dropped and
          <span class="font-medium">no rows are removed</span>. Preview the impact below.
        </p>

        <!-- Preview panel -->
        <div class="rounded-3 border border-outline-gray-1 bg-surface-gray-1 px-3 py-2.5">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-ink-gray-7">Preview (dry run)</span>
            <button
              type="button"
              class="inline-flex items-center gap-1 rounded-2 px-2 py-1 text-xs font-medium text-primary hover:bg-primary-1 disabled:cursor-not-allowed disabled:text-ink-gray-4"
              :disabled="!!validationError || previewing || !sessionUuid"
              @click="runPreview"
            >
              <Loader2 v-if="previewing" class="h-3 w-3 animate-spin" />
              <Play v-else class="h-3 w-3" />
              Refresh
            </button>
          </div>

          <p v-if="validationError" class="mt-2 text-xs text-ink-gray-5">{{ validationError }}</p>
          <p v-else-if="previewError" class="mt-2 flex items-start gap-1.5 text-xs text-ink-red">
            <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" /> {{ previewError }}
          </p>
          <template v-else-if="preview">
            <p class="mt-2 text-sm text-ink-gray-9">
              {{ preview.row_count_before.toLocaleString() }} →
              <span class="font-semibold">{{ preview.row_count_after.toLocaleString() }}</span> rows
              <span
                v-if="delta !== 0"
                class="ml-1 text-xs font-medium"
                :class="delta < 0 ? 'text-ink-red' : 'text-ink-green'"
              >
                ({{ delta > 0 ? '+' : '' }}{{ delta.toLocaleString() }})
              </span>
              <span v-else class="ml-1 text-xs text-ink-gray-5">(no row change)</span>
            </p>
            <p
              v-if="preview.coerced_null_count != null"
              class="mt-1.5 flex items-start gap-1.5 text-xs"
              :class="preview.coerced_null_count > 0 ? 'text-ink-red' : 'text-ink-green'"
            >
              <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span v-if="preview.coerced_null_count > 0">
                {{ preview.coerced_null_count.toLocaleString() }}
                value{{ preview.coerced_null_count === 1 ? '' : 's' }} can't be parsed as
                {{ form.newType }} and will be set to NULL.
              </span>
              <span v-else>All values parse as {{ form.newType }} — none will be nulled.</span>
            </p>
            <details class="mt-2">
              <summary class="cursor-pointer text-[11px] text-ink-gray-5 hover:text-ink-gray-7">Compiled SQL</summary>
              <pre class="mt-1 max-h-32 overflow-auto rounded-2 bg-surface-gray-3 p-2 text-[11px] leading-relaxed text-ink-gray-8">{{ preview.compiled_sql }}</pre>
            </details>
          </template>
          <p v-else class="mt-2 text-xs text-ink-gray-4">Adjust the fields above to preview the impact.</p>
        </div>

        <p v-if="applyError" class="flex items-start gap-1.5 text-xs text-ink-red">
          <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" /> {{ applyError }}
        </p>
      </div>

      <!-- Footer -->
      <div class="flex items-center justify-end gap-2 border-t border-outline-gray-1 px-5 py-3">
        <button
          type="button"
          class="rounded-3 px-3 py-1.5 text-sm font-medium text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-8"
          @click="close"
        >
          Cancel
        </button>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-3 bg-primary px-4 py-1.5 text-sm font-medium text-ink-white shadow-sm hover:bg-primary-7 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!!validationError || applying"
          @click="apply"
        >
          <Loader2 v-if="applying" class="h-4 w-4 animate-spin" />
          Apply
        </button>
      </div>
    </div>
  </div>
</template>
