<script setup lang="ts">
// Query Engine pillar: a MySQL-Workbench-style SQL console with AI NL->SQL assist
// (QueryConsole) plus the business dictionary (CustomInstructions), fronted by the
// auto-EDA Suggested Questions strip (#26) — click one and it drops into the console
// below. Runs against the loaded dataset, so the whole surface is gated until a
// session exists.
import { Database } from '@lucide/vue'
import { useSession } from '../composables/useSession'
import SuggestedQuestions from '../components/SuggestedQuestions.vue'
import QueryConsole from '../components/QueryConsole.vue'
import CustomInstructions from '../components/CustomInstructions.vue'

const { sessionUuid } = useSession()
</script>

<template>
  <div v-if="sessionUuid" class="space-y-6">
    <SuggestedQuestions />
    <div class="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <QueryConsole />
      <CustomInstructions />
    </div>
  </div>
  <div
    v-else
    class="flex min-h-[350px] flex-col items-center justify-center rounded-5 border border-dashed border-outline-gray-3 bg-surface-base p-8 text-center"
  >
    <Database class="mb-3 h-8 w-8 text-ink-gray-4" />
    <h3 class="text-sm font-medium text-ink-gray-9">No data loaded</h3>
    <p class="mt-1 text-xs text-ink-gray-5">Load a dataset in the Table tab to query it.</p>
  </div>
</template>
