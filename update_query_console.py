import sys
import re

with open('frontend/src/components/QueryConsole.vue', 'r', encoding='utf-8') as f:
    content = f.read()

# Add imports for api.ts changes
content = content.replace("import { askQuestion, sqlAssist, executeSql, exportRows, apiErrorMessage } from '../services/api'", 
                          "import { askQuestion, sqlAssist, executeSql, streamQueryProgress, cancelQuery, exportRows, apiErrorMessage } from '../services/api'")

# Add state variables
if "const queryId = ref<string | null>(null)" not in content:
    content = content.replace("const running = ref(false)", "const running = ref(false)\nconst queryId = ref<string | null>(null)\nconst elapsedMs = ref(0)")

# Update run() logic
new_run = """async function run(): Promise<void> {
  const uuid = sessionUuid.value
  const sql = sqlText.value.trim()
  if (!uuid || !sql || running.value) return
  running.value = true
  runError.value = null
  elapsedMs.value = 0
  queryId.value = null
  
  try {
    const startRes = await executeSql(uuid, sql)
    queryId.value = startRes.query_id
    
    if (uuid !== sessionUuid.value) return
    
    const res = await streamQueryProgress(uuid, queryId.value, (ms) => {
      elapsedMs.value = ms
    })
    
    result.value = res
    lastRanSql.value = sql
    recordRun({ sql, ok: true, rowCount: res.row_count })
  } catch (e) {
    if (uuid === sessionUuid.value) {
      const msg = apiErrorMessage(e)
      runError.value = msg
      result.value = null
      recordRun({ sql, ok: false, error: msg })
    }
  } finally {
    if (uuid === sessionUuid.value) {
      running.value = false
      queryId.value = null
    }
  }
}

async function abortQuery() {
  if (sessionUuid.value && queryId.value) {
    try {
      await cancelQuery(sessionUuid.value, queryId.value)
    } catch (e) {
      console.error("Cancel failed:", e)
    }
  }
}"""

content = re.sub(r'async function run\(\): Promise<void> \{.*?if \(uuid === sessionUuid\.value\) running\.value = false\n  \}\n\}', new_run, content, flags=re.DOTALL)

# Add template UI for Cancel/Progress
# We replace the Run button block with one that supports cancelling
button_target = """        <button
          type="button"
          class="flex items-center gap-1.5 rounded-md bg-primary-6 px-3 py-1.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-7 disabled:opacity-50"
          :disabled="running || !sqlText.trim()"
          @click="run"
        >
          <Play v-if="!running" class="h-4 w-4" />
          <Loader2 v-else class="h-4 w-4 animate-spin" />
          Run
        </button>"""

button_replacement = """        <div class="flex items-center gap-2">
          <span v-if="running" class="text-xs text-ink-gray-5 font-medium tabular-nums">{{ (elapsedMs / 1000).toFixed(1) }}s</span>
          <button
            v-if="running"
            type="button"
            class="flex items-center gap-1.5 rounded-md bg-red-50 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-100 transition-colors border border-red-200"
            @click="abortQuery"
          >
            <Square class="h-4 w-4" />
            Cancel
          </button>
          <button
            v-else
            type="button"
            class="flex items-center gap-1.5 rounded-md bg-primary-6 px-3 py-1.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-7 disabled:opacity-50"
            :disabled="!sqlText.trim()"
            @click="run"
          >
            <Play class="h-4 w-4" />
            Run
          </button>
        </div>"""

content = content.replace(button_target, button_replacement)

# Import Square icon if not present
if "Square" not in content:
    content = content.replace("Play, Copy,", "Play, Copy, Square,")

with open('frontend/src/components/QueryConsole.vue', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated QueryConsole.vue")
