<script setup lang="ts">
import { Database } from '@lucide/vue'
import { useSession } from '../composables/useSession'
import AIQueryBox from '../components/AIQueryBox.vue'
import CustomInstructions from '../components/CustomInstructions.vue'

// The Query Engine runs against the loaded dataset; gate it until a session exists.
// A MySQL-Workbench-style SQL editor (with AI NL->SQL assist) replaces this shell in a
// later task; for now it hosts the existing query + instructions components.
const { sessionUuid } = useSession()
</script>

<template>
  <div v-if="sessionUuid" class="space-y-8">
    <AIQueryBox />
    <CustomInstructions />
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
