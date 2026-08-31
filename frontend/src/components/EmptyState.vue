<script setup lang="ts">
// Shared calm empty-state (Batch 8 / Structural polish). Replaces the bare dashed-text
// placeholders the Canvas (no tiles) and Query (no results) used to show. A branded
// line-art area + headline + subtext + an optional actions slot. Token-styled, no
// hard-coded colours — the art inherits `currentColor` so it tracks the primary accent.
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <div
    class="flex flex-col items-center justify-center rounded-5 border border-dashed border-outline-gray-2 bg-surface-base px-6 py-12 text-center"
  >
    <div class="mb-4 text-primary/70">
      <slot name="art" />
    </div>
    <h3 class="text-sm font-semibold text-ink-gray-8">{{ title }}</h3>
    <p v-if="subtitle" class="mt-1 max-w-sm text-xs leading-relaxed text-ink-gray-5">{{ subtitle }}</p>
    <div v-if="$slots.actions" class="mt-5 flex flex-wrap items-center justify-center gap-2">
      <slot name="actions" />
    </div>
  </div>
</template>
