<script setup lang="ts">
import { useSession } from '../composables/useSession'
import ChartCanvas from '../components/ChartCanvas.vue'
import EmptyState from '../components/EmptyState.vue'

// Charts need a loaded dataset; the session is shared across views via the singleton.
const { sessionUuid } = useSession()
</script>

<template>
  <ChartCanvas v-if="sessionUuid" />
  <EmptyState
    v-else
    title="No data loaded yet"
    subtitle="Drop a dataset in the Table tab and Spencer will suggest a chart layout you can refine."
  >
    <template #art>
      <svg
        width="76" height="56" viewBox="0 0 76 56" fill="none"
        stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
        aria-hidden="true"
      >
        <rect x="10" y="9" width="56" height="40" rx="7" />
        <path d="M20 42V32M32 42V23M44 42V29M56 42V16" />
        <circle cx="56" cy="16" r="3" fill="currentColor" stroke="none" />
      </svg>
    </template>
    <template #actions>
      <RouterLink
        to="/table"
        class="inline-flex items-center gap-1.5 rounded-3 bg-primary px-4 py-2 text-sm font-medium text-ink-white shadow-sm transition-colors hover:bg-primary-7"
      >
        Go to Table
      </RouterLink>
    </template>
  </EmptyState>
</template>
