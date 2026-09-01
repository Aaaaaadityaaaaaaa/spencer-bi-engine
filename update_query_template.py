import sys
import re

with open('frontend/src/components/QueryConsole.vue', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the run button block
old_run_btn = """          <button
            type="button"
            class="btn btn-ghost"
            :disabled="running || !sqlText.trim()"
            @click="run"
          >
            <Loader2 v-if="running" class="h-4 w-4 animate-spin text-primary" />
            <Play v-else class="h-4 w-4 text-primary" />
            Run
          </button>"""

new_run_btn = """          <div class="flex items-center gap-2">
            <span v-if="running" class="text-xs text-ink-gray-5 font-medium tabular-nums">{{ (elapsedMs / 1000).toFixed(1) }}s</span>
            <button
              v-if="running"
              type="button"
              class="btn btn-ghost text-ink-red hover:bg-red-50"
              @click="abortQuery"
            >
              <Square class="h-4 w-4" /> Cancel
            </button>
            <button
              v-else
              type="button"
              class="btn btn-ghost"
              :disabled="!sqlText.trim()"
              @click="run"
            >
              <Play class="h-4 w-4 text-primary" /> Run
            </button>
          </div>"""

content = content.replace(old_run_btn, new_run_btn)

with open('frontend/src/components/QueryConsole.vue', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated QueryConsole.vue with Cancel button")
