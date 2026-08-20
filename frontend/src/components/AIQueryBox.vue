<script setup lang="ts">
</script>

<template>
  <div class="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
    <div class="p-4 border-b border-gray-200">
      <h3 class="text-sm font-semibold text-gray-700 mb-2">Ask AI</h3>
      <div class="flex space-x-2">
        <input type="text" class="flex-1 border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500 text-sm py-2 px-3" placeholder="e.g., Show me profit margins by region for Q3">
        <button class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-md text-sm font-medium shadow-sm transition-colors">Ask</button>
      </div>
    </div>
    <!-- AI Feedback / Review Gate Area -->
    <div class="bg-gray-50 p-4 text-sm text-gray-500 border-b border-gray-200 hidden">
      <div class="font-mono bg-gray-100 p-2 rounded text-xs text-gray-800 mb-2 border border-gray-200">
        SELECT region, SUM(profit)/SUM(revenue) as margin FROM ...
      </div>
      <div class="flex justify-end space-x-2">
         <button class="px-3 py-1 bg-white border border-gray-300 text-gray-700 rounded shadow-sm text-xs hover:bg-gray-50">Edit</button>
         <button class="px-3 py-1 bg-indigo-600 text-white rounded shadow-sm text-xs hover:bg-indigo-700">Execute</button>
      </div>
    </div>
  </div>
</template>
