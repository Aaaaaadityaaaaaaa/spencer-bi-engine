<script setup lang="ts">
</script>

<template>
  <div class="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden flex flex-col min-h-[350px]">
    <div class="px-4 py-3 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
      <h3 class="text-sm font-semibold text-gray-700">Chart Canvas</h3>
      <div class="flex space-x-2">
        <select class="text-xs border-gray-300 rounded-md shadow-sm focus:border-indigo-500 focus:ring-indigo-500 py-1 pl-2 pr-6">
          <option>Bar Chart</option>
          <option>Line Chart</option>
          <option>Scatter</option>
        </select>
      </div>
    </div>
    <div class="flex-1 p-4 flex items-center justify-center text-gray-400 text-sm">
      Configure axes to render chart
    </div>
  </div>
</template>
