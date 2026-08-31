<script setup lang="ts">
import { ref } from 'vue'
import { Upload, Loader2, FileSpreadsheet, RefreshCw } from '@lucide/vue'
import { useSession } from '../composables/useSession'

const { columns, rowCount, uploading, error, sessionUuid, fileName, upload } = useSession()

const fileInput = ref<HTMLInputElement | null>(null)
const dragActive = ref(false)
// Local copy of the picked name so the "Uploading …" label has it before the
// session's fileName lands (that's only set once createSession resolves).
const pendingName = ref<string | null>(null)

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
  pendingName.value = file.name
  void upload(file)
}

// Which empty-state tab is showing. "paste" lets the user drop raw CSV/TSV text in
// (no file needed); it is wrapped in a File and sent through the same upload() path.
const mode = ref<'upload' | 'paste'>('upload')
const pasteText = ref('')

// Turn pasted text into a File and upload it. The delimiter is sniffed from the first
// line -- more tabs than commas => .tsv, else .csv -- so the backend's extension
// dispatch (read_csv_auto with the matching delimiter) parses it. The backend still
// infers columns/types; the first row is treated as the header.
function submitPaste() {
  const text = pasteText.value
  if (!text.trim()) return
  const nl = text.indexOf('\n')
  const firstLine = nl === -1 ? text : text.slice(0, nl)
  const tabs = (firstLine.match(/\t/g) ?? []).length
  const commas = (firstLine.match(/,/g) ?? []).length
  const ext = tabs > commas ? 'tsv' : 'csv'
  const type = ext === 'tsv' ? 'text/tab-separated-values' : 'text/csv'
  handleFile(new File([text], `pasted.${ext}`, { type }))
}
</script>

<template>
  <div>
    <!-- File input is always mounted so "Replace" works from the loaded bar too. -->
    <input
      ref="fileInput"
      type="file"
      accept=".csv,.tsv,.parquet,.json,.xlsx"
      class="hidden"
      @change="onFileChange"
    />

    <!-- Loaded: the dropzone collapses to a slim bar so the table can take over. -->
    <div
      v-if="sessionUuid || uploading"
      class="flex items-center gap-3 rounded-5 border border-outline-gray-1 bg-surface-base px-4 py-3 shadow-sm"
    >
      <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-4 bg-primary-1 text-primary">
        <Loader2 v-if="uploading" class="h-4 w-4 animate-spin" />
        <FileSpreadsheet v-else class="h-4 w-4" />
      </div>
      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-medium text-ink-gray-9">
          {{ uploading ? 'Uploading ' + (pendingName ?? 'file') + '…' : (fileName ?? 'Data loaded') }}
        </p>
        <p class="truncate text-xs text-ink-gray-5">
          <template v-if="uploading">Ingesting and profiling your data</template>
          <template v-else>{{ rowCount.toLocaleString() }} rows · {{ columns.length }} columns</template>
        </p>
      </div>
      <button
        v-if="!uploading"
        type="button"
        class="btn btn-ghost shrink-0"
        @click="browse"
      >
        <RefreshCw class="h-3.5 w-3.5" /> Replace
      </button>
    </div>

    <!-- Empty: tabbed upload / paste. -->
    <div v-else>
      <div class="mb-2 inline-flex rounded-3 border border-outline-gray-2 bg-surface-gray-1 p-0.5 text-xs">
        <button
          type="button"
          class="rounded-2 px-3 py-1 font-medium transition-colors"
          :class="mode === 'upload' ? 'bg-surface-base text-ink-gray-9 shadow-sm' : 'text-ink-gray-5 hover:text-ink-gray-8'"
          @click="mode = 'upload'"
        >
          Upload file
        </button>
        <button
          type="button"
          class="rounded-2 px-3 py-1 font-medium transition-colors"
          :class="mode === 'paste' ? 'bg-surface-base text-ink-gray-9 shadow-sm' : 'text-ink-gray-5 hover:text-ink-gray-8'"
          @click="mode = 'paste'"
        >
          Paste data
        </button>
      </div>

      <!-- Upload dropzone -->
      <div
        v-if="mode === 'upload'"
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
        <div class="mb-2 text-primary">
          <Upload class="h-8 w-8" />
        </div>
        <h3 class="text-sm font-medium text-ink-gray-9">Upload a data file</h3>
        <p class="mt-1 text-xs text-ink-gray-5">Drag and drop, or click to browse</p>
        <p class="mt-1 text-[11px] text-ink-gray-4">CSV, TSV, Parquet, JSON, or Excel (.xlsx)</p>
      </div>

      <!-- Paste box -->
      <div v-else class="rounded-5 border-2 border-dashed border-outline-gray-3 bg-surface-base p-4">
        <textarea
          v-model="pasteText"
          rows="6"
          placeholder="Paste rows here — comma- or tab-separated, first row as the header…"
          class="w-full resize-y rounded-4 border border-outline-gray-2 bg-surface-gray-2 p-2 font-mono text-xs text-ink-gray-9 outline-none placeholder:text-ink-gray-4 focus:border-primary-3"
        ></textarea>
        <div class="mt-2 flex items-center justify-between gap-3">
          <span class="text-[11px] text-ink-gray-4">First row = column headers · comma or tab separated</span>
          <button
            type="button"
            class="inline-flex shrink-0 items-center gap-1.5 rounded-3 bg-primary px-3 py-1.5 text-xs font-medium text-ink-white shadow-sm transition-colors hover:bg-primary-7 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="!pasteText.trim()"
            @click="submitPaste"
          >
            <FileSpreadsheet class="h-3.5 w-3.5" /> Load pasted data
          </button>
        </div>
      </div>
    </div>

    <p v-if="error" class="mt-2 text-xs text-ink-red">{{ error }}</p>
  </div>
</template>
