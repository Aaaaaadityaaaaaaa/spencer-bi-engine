<template>
  <div v-if="error" class="error-boundary bg-red-50 border border-red-200 rounded-lg p-4 m-2 flex flex-col items-center justify-center text-center shadow-sm h-full w-full">
    <AlertCircle class="w-8 h-8 text-red-500 mb-2" />
    <h3 class="text-sm font-semibold text-red-800 mb-1">Something went wrong here.</h3>
    <p class="text-xs text-red-600 max-w-xs break-words">{{ error.message }}</p>
    <button @click="resetError" class="mt-3 px-3 py-1 bg-red-100 hover:bg-red-200 text-red-700 text-xs font-medium rounded transition-colors">
      Try Again
    </button>
  </div>
  <slot v-else></slot>
</template>

<script setup lang="ts">
import { ref, onErrorCaptured } from 'vue';
import { AlertCircle } from '@lucide/vue';

const error = ref<Error | null>(null);

onErrorCaptured((err: unknown, _instance, info) => {
  console.error("ErrorBoundary caught an error:", err, info);
  error.value = err instanceof Error ? err : new Error(String(err));
  // Return false to prevent the error from propagating further up (white screen of death)
  return false;
});

const resetError = () => {
  error.value = null;
};
</script>
