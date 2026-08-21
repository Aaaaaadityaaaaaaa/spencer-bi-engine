<script setup lang="ts">
import { ref } from 'vue'
import { Upload, Loader2 } from '@lucide/vue'
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
      class="flex min-h-[160px] cursor-pointer flex-col items-center justify-center rounded-5 border-2 border-dashed bg-surface-base p-6 transition-colors"
      :class="dragActive
        ? 'border-primary-5 bg-primary-1'
        : 'border-outline-gray-3 hover:border-primary-3 hover:bg-primary-1'"
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

      <div class="mb-2 text-primary">
        <Loader2 v-if="uploading" class="h-8 w-8 animate-spin" />
        <Upload v-else class="h-8 w-8" />
      </div>

      <template v-if="uploading">
        <h3 class="text-sm font-medium text-ink-gray-9">Uploading{{ fileName ? ' ' + fileName : '' }}…</h3>
        <p class="mt-1 text-xs text-ink-gray-5">Ingesting and profiling your data</p>
      </template>
      <template v-else-if="sessionUuid">
        <h3 class="text-sm font-medium text-ink-gray-9">{{ fileName ?? 'Data loaded' }}</h3>
        <p class="mt-1 text-xs text-ink-gray-5">
          {{ rowCount.toLocaleString() }} rows · {{ columns.length }} columns — click to replace
        </p>
      </template>
      <template v-else>
        <h3 class="text-sm font-medium text-ink-gray-9">Upload CSV or Parquet</h3>
        <p class="mt-1 text-xs text-ink-gray-5">Drag and drop, or click to browse</p>
      </template>
    </div>

    <p v-if="error" class="mt-2 text-xs text-ink-red">{{ error }}</p>

    <!-- Schema pills rendered from the POST /sessions response -->
    <div v-if="sessionUuid && columns.length" class="mt-3 flex flex-wrap gap-2">
      <span
        v-for="col in columns"
        :key="col.name"
        class="inline-flex items-center gap-1.5 rounded-3 border border-outline-gray-1 bg-surface-gray-2 px-2 py-1 text-xs"
      >
        <span class="font-medium text-ink-gray-8">{{ col.name }}</span>
        <span class="uppercase tracking-wide text-ink-gray-4">{{ col.type }}</span>
      </span>
    </div>
  </div>
</template>
