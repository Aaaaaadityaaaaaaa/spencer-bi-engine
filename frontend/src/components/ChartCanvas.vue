<script setup lang="ts">
import { BarChart3 } from '@lucide/vue'
</script>

<template>
  <div class="flex min-h-[350px] flex-col overflow-hidden rounded-5 border border-outline-gray-1 bg-surface-base shadow-sm">
    <div class="flex items-center justify-between border-b border-outline-gray-1 bg-surface-gray-1 px-4 py-3">
      <h3 class="flex items-center gap-1.5 text-sm font-semibold text-ink-gray-8">
        <BarChart3 class="h-4 w-4 text-primary" /> Chart Canvas
      </h3>
      <div class="flex gap-2">
        <select class="rounded-4 border border-outline-gray-2 bg-surface-gray-2 py-1 pl-2 pr-6 text-xs text-ink-gray-8 transition-colors hover:bg-surface-gray-3 focus:border-outline-gray-4 focus:bg-surface-base focus:outline-none">
          <option>Bar Chart</option>
          <option>Line Chart</option>
          <option>Scatter</option>
        </select>
      </div>
    </div>
    <div class="flex flex-1 items-center justify-center p-4 text-sm text-ink-gray-4">
      Configure axes to render chart
    </div>
  </div>
</template>
