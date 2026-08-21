<script setup lang="ts">
import { Plus, Trash2 } from '@lucide/vue'
</script>

<template>
  <div class="min-h-[250px] overflow-hidden rounded-5 border border-outline-gray-1 bg-surface-base shadow-sm">
    <div class="flex items-center justify-between border-b border-outline-gray-1 bg-surface-gray-1 px-4 py-3">
      <h3 class="text-sm font-semibold text-ink-gray-8">Custom Instructions</h3>
      <button class="inline-flex items-center gap-1 text-xs font-medium text-primary transition-colors hover:text-primary-7">
        <Plus class="h-3.5 w-3.5" /> Add
      </button>
    </div>
    <div class="space-y-4 p-4">
      <div class="mb-4 text-xs leading-relaxed text-ink-gray-5">
        Define business logic and terms for the AI.
      </div>

      <!-- Example Item -->
      <div class="group rounded-4 border border-outline-gray-1 bg-surface-gray-1 p-3">
        <div class="mb-1 flex items-start justify-between">
          <span class="text-sm font-semibold text-ink-gray-8">active users</span>
          <button class="text-ink-gray-4 opacity-0 transition-opacity hover:text-ink-red group-hover:opacity-100">
            <Trash2 class="h-4 w-4" />
          </button>
        </div>
        <p class="font-mono text-xs text-ink-gray-6">logged in within 30 days AND spent &gt; $10</p>
      </div>
    </div>
  </div>
</template>
