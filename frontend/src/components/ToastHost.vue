<script setup lang="ts">
// Renders the global toast queue (Batch 1 / Global). Additive: mounted once at the app
// root by App.vue. Reads the shared useToasts() bus.
import { CheckCircle2, AlertCircle, Info, X } from '@lucide/vue'
import { useToasts } from '../composables/useToast'

const { toasts, dismissToast } = useToasts()

const iconFor = (kind: string) => (kind === 'success' ? CheckCircle2 : kind === 'error' ? AlertCircle : Info)
const accentFor = (kind: string) =>
  kind === 'success' ? 'text-ink-green-7' : kind === 'error' ? 'text-ink-red-6' : 'text-primary-6'
</script>

<template>
  <div class="pointer-events-none fixed bottom-4 right-4 z-[70] flex w-80 flex-col gap-2">
    <TransitionGroup name="toast">
      <div
        v-for="t in toasts"
        :key="t.id"
        data-toast
        :data-toast-kind="t.kind"
        class="pointer-events-auto flex items-start gap-2.5 rounded-5 border border-outline-gray-2 bg-surface-base px-3 py-2.5 shadow-md"
      >
        <component :is="iconFor(t.kind)" class="mt-0.5 h-4 w-4 shrink-0" :class="accentFor(t.kind)" />
        <p class="min-w-0 flex-1 text-xs text-ink-gray-8">{{ t.message }}</p>
        <button
          v-if="t.actionLabel"
          type="button"
          class="shrink-0 rounded-2 px-1.5 py-0.5 text-xs font-medium text-primary-6 hover:bg-primary-1"
          @click="t.onAction?.(); dismissToast(t.id)"
        >
          {{ t.actionLabel }}
        </button>
        <button
          type="button"
          class="shrink-0 rounded-2 p-0.5 text-ink-gray-4 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-7"
          @click="dismissToast(t.id)"
        >
          <X class="h-3.5 w-3.5" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
