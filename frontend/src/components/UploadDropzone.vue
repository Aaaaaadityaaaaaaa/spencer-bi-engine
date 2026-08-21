<script setup lang="ts">
import { ref } from 'vue'
import { useSession } from '../composables/useSession'

const { columns, rowCount, uploading, error, sessionUuid, upload } = useSession()

const fileInput = ref<HTMLInputElement | null>(null)
const dragActive = ref(false)
const fileName = ref<string | null>(null)

function browse() {
  fileInput.value?.click()
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) handleFile(file)
  input.value = '' // reset so re-selecting the same file still fires `change`
}

function onDrop(e: DragEvent) {
  dragActive.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) handleFile(file)
}

function handleFile(file: File) {
  fileName.value = file.name
  void upload(file)
}
</script>

<template>
  <div>
    <div
      class="bg-white p-6 rounded-xl border-2 border-dashed transition-colors cursor-pointer flex flex-col items-center justify-center min-h-[160px]"
      :class="dragActive ? 'border-indigo-400 bg-indigo-50' : 'border-indigo-200 hover:bg-indigo-50'"
      role="button"
      tabindex="0"
      @click="browse"
      @keydown.enter="browse"
      @dragover.prevent="dragActive = true"
      @dragleave.prevent="dragActive = false"
      @drop.prevent="onDrop"
    >
      <input
        ref="fileInput"
        type="file"
        accept=".csv,.parquet"
        class="hidden"
        @change="onFileChange"
      />

      <div class="text-indigo-600 mb-2">
        <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path></svg>
      </div>

      <template v-if="uploading">
        <h3 class="text-sm font-medium text-gray-900">Uploading{{ fileName ? ' ' + fileName : '' }}…</h3>
        <p class="text-xs text-gray-500 mt-1">Ingesting and profiling your data</p>
      </template>
      <template v-else-if="sessionUuid">
        <h3 class="text-sm font-medium text-gray-900">{{ fileName ?? 'Data loaded' }}</h3>
        <p class="text-xs text-gray-500 mt-1">
          {{ rowCount.toLocaleString() }} rows · {{ columns.length }} columns — click to replace
        </p>
      </template>
      <template v-else>
        <h3 class="text-sm font-medium text-gray-900">Upload CSV or Parquet</h3>
        <p class="text-xs text-gray-500 mt-1">Drag and drop, or click to browse</p>
      </template>
    </div>

    <p v-if="error" class="mt-2 text-xs text-red-600">{{ error }}</p>

    <!-- Schema pills rendered from the POST /sessions response -->
    <div v-if="sessionUuid && columns.length" class="mt-3 flex flex-wrap gap-2">
      <span
        v-for="col in columns"
        :key="col.name"
        class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-gray-100 text-xs"
      >
        <span class="font-medium text-gray-800">{{ col.name }}</span>
        <span class="text-gray-400 uppercase tracking-wide">{{ col.type }}</span>
      </span>
    </div>
  </div>
</template>
