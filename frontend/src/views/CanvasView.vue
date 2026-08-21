<script setup lang="ts">
import { BarChart3 } from '@lucide/vue'
import { useSession } from '../composables/useSession'
import ChartCanvas from '../components/ChartCanvas.vue'

// Charts need a loaded dataset; the session is shared across views via the singleton.
const { sessionUuid } = useSession()
</script>

<template>
  <ChartCanvas v-if="sessionUuid" />
  <div
    v-else
    class="flex min-h-[350px] flex-col items-center justify-center rounded-5 border border-dashed border-outline-gray-3 bg-surface-base p-8 text-center"
  >
    <BarChart3 class="mb-3 h-8 w-8 text-ink-gray-4" />
    <h3 class="text-sm font-medium text-ink-gray-9">No data loaded</h3>
    <p class="mt-1 text-xs text-ink-gray-5">Load a dataset in the Table tab to build a chart.</p>
  </div>
</template>
