<script setup lang="ts">
import { Sparkles } from '@lucide/vue'
</script>

<template>
  <div class="overflow-hidden rounded-5 border border-outline-gray-1 bg-surface-base shadow-sm">
    <div class="border-b border-outline-gray-1 p-4">
      <h3 class="mb-2 flex items-center gap-1.5 text-sm font-semibold text-ink-gray-8">
        <Sparkles class="h-4 w-4 text-primary" /> Ask AI
      </h3>
      <div class="flex gap-2">
        <input
          type="text"
          class="flex-1 rounded-4 border border-outline-gray-2 bg-surface-gray-2 px-3 py-2 text-sm text-ink-gray-8 placeholder-ink-gray-4 transition-colors hover:bg-surface-gray-3 focus:border-outline-gray-4 focus:bg-surface-base focus:outline-none"
          placeholder="e.g., Show me profit margins by region for Q3"
        />
        <button class="rounded-3 bg-primary px-4 py-2 text-sm font-medium text-ink-white shadow-sm transition-colors hover:bg-primary-7">
          Ask
        </button>
      </div>
    </div>
    <!-- AI Feedback / Review Gate Area (placeholder, hidden until the AI path is wired) -->
    <div class="hidden border-b border-outline-gray-1 bg-surface-gray-1 p-4 text-sm text-ink-gray-5">
      <div class="mb-2 rounded-3 border border-outline-gray-1 bg-surface-gray-2 p-2 font-mono text-xs text-ink-gray-8">
        SELECT region, SUM(profit)/SUM(revenue) as margin FROM ...
      </div>
      <div class="flex justify-end gap-2">
        <button class="rounded-3 border border-outline-gray-2 bg-surface-base px-3 py-1 text-xs text-ink-gray-7 shadow-sm hover:bg-surface-gray-2">Edit</button>
        <button class="rounded-3 bg-primary px-3 py-1 text-xs text-ink-white shadow-sm hover:bg-primary-7">Execute</button>
      </div>
    </div>
  </div>
</template>
