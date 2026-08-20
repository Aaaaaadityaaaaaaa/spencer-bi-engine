<script setup lang="ts">
</script>

<template>
  <div class="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden min-h-[250px]">
    <div class="px-4 py-3 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
      <h3 class="text-sm font-semibold text-gray-700">Custom Instructions</h3>
      <button class="text-indigo-600 hover:text-indigo-800 text-xs font-medium">+ Add</button>
    </div>
    <div class="p-4 space-y-4">
      <div class="text-xs text-gray-500 leading-relaxed mb-4">
        Define business logic and terms for the AI.
      </div>
      
      <!-- Example Item -->
      <div class="border border-gray-200 rounded-lg p-3 bg-gray-50 group">
        <div class="flex justify-between items-start mb-1">
          <span class="font-semibold text-sm text-gray-800">active users</span>
          <button class="text-gray-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
          </button>
        </div>
        <p class="text-xs text-gray-600 font-mono">logged in within 30 days AND spent > $10</p>
      </div>
      
    </div>
  </div>
</template>
