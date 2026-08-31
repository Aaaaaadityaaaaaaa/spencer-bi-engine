<script setup lang="ts">
// Query Engine pillar: a MySQL-Workbench-style SQL console with AI NL->SQL assist
// (QueryConsole) plus the business dictionary (CustomInstructions), fronted by the
// auto-EDA Suggested Questions strip (#26) — click one and it drops into the console
// below. Runs against the loaded dataset, so the whole surface is gated until a
// session exists.
import { useSession } from '../composables/useSession'
import SuggestedQuestions from '../components/SuggestedQuestions.vue'
import QueryConsole from '../components/QueryConsole.vue'
import CustomInstructions from '../components/CustomInstructions.vue'
import EmptyState from '../components/EmptyState.vue'

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
  <EmptyState
    v-else
    title="No data loaded yet"
    subtitle="Load a dataset in the Table tab, then ask Spencer in plain English — it writes and shows you the SQL before it runs."
  >
    <template #art>
      <svg
        width="76" height="56" viewBox="0 0 76 56" fill="none"
        stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
        aria-hidden="true"
      >
        <ellipse cx="38" cy="15" rx="22" ry="8" />
        <path d="M16 15v26c0 4.4 9.9 8 22 8s22-3.6 22-8V15" />
        <path d="M16 28c0 4.4 9.9 8 22 8s22-3.6 22-8" />
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
