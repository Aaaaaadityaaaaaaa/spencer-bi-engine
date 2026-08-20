<script setup lang="ts">
import UploadDropzone from './components/UploadDropzone.vue'
import DataGrid from './components/DataGrid.vue'
import ChartCanvas from './components/ChartCanvas.vue'
import AIQueryBox from './components/AIQueryBox.vue'
import CustomInstructions from './components/CustomInstructions.vue'
</script>

<template>
  <div class="flex h-screen bg-gray-50 font-sans text-gray-900">
    <!-- Sidebar -->
    <aside class="w-64 bg-white border-r border-gray-200 flex flex-col">
      <div class="h-16 flex items-center px-6 border-b border-gray-200">
        <h1 class="text-xl font-bold text-indigo-600">Project Spencer</h1>
      </div>
      <nav class="flex-1 p-4 space-y-2">
        <a href="#" class="block px-4 py-2 rounded-md bg-indigo-50 text-indigo-700 font-medium">Data Workspace</a>
        <a href="#" class="block px-4 py-2 rounded-md hover:bg-gray-50 text-gray-700">Scheduled Runs</a>
        <a href="#" class="block px-4 py-2 rounded-md hover:bg-gray-50 text-gray-700">Settings</a>
      </nav>
    </aside>

    <!-- Main Content -->
    <main class="flex-1 flex flex-col overflow-hidden">
      <header class="h-16 bg-white border-b border-gray-200 flex items-center px-8 justify-between shadow-sm">
        <h2 class="text-lg font-medium">Data Workspace</h2>
        <div class="flex space-x-2">
           <button class="px-3 py-1.5 text-sm font-medium text-gray-600 hover:text-gray-900 bg-white border border-gray-300 rounded-md shadow-sm">Undo</button>
           <button class="px-3 py-1.5 text-sm font-medium text-gray-600 hover:text-gray-900 bg-white border border-gray-300 rounded-md shadow-sm">Redo</button>
        </div>
      </header>
      
      <div class="flex-1 overflow-auto p-8 space-y-8">
        <!-- Components Shell -->
        <UploadDropzone />
        
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
          <div class="lg:col-span-2 space-y-8">
            <AIQueryBox />
            <DataGrid />
            <ChartCanvas />
          </div>
          
          <div class="space-y-8">
            <CustomInstructions />
          </div>
        </div>
      </div>
    </main>
  </div>
</template>
