<script setup lang="ts">
// The business dictionary (Custom Instructions): term -> definition pairs that feed
// the NL->SQL prompt. Real CRUD against /sessions/{id}/instructions; every add/delete
// bumps bizdict_version server-side, so cached AI SQL is invalidated automatically.
//
// The parent view gates this on sessionUuid, but the session can CHANGE under us (a
// "Replace" upload keeps this mounted with a new uuid), so we reload on sessionUuid.
// Both async reads carry the uuid-staleness guard used across the app.
import { ref, watch } from 'vue'
import { Plus, Trash2, Loader2, AlertCircle } from '@lucide/vue'
import { useSession } from '../composables/useSession'
import {
  fetchInstructions,
  addInstruction,
  deleteInstruction,
  apiErrorMessage,
} from '../services/api'
import type { CustomInstruction } from '../types'

const { sessionUuid } = useSession()

const items = ref<CustomInstruction[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const showForm = ref(false)
const term = ref('')
const definition = ref('')
const saving = ref(false)

async function load(): Promise<void> {
  const uuid = sessionUuid.value
  if (!uuid) {
    items.value = []
    return
  }
  loading.value = true
  error.value = null
  try {
    const res = await fetchInstructions(uuid)
    if (uuid !== sessionUuid.value) return // session switched mid-flight -> drop
    items.value = res
  } catch (e) {
    if (uuid === sessionUuid.value) error.value = apiErrorMessage(e)
  } finally {
    if (uuid === sessionUuid.value) loading.value = false
  }
}

// Reload whenever the session changes (including the first mount).
watch(sessionUuid, load, { immediate: true })

async function save(): Promise<void> {
  const uuid = sessionUuid.value
  const t = term.value.trim()
  const d = definition.value.trim()
  if (!uuid || !t || !d || saving.value) return
  saving.value = true
  error.value = null
  try {
    await addInstruction(uuid, { term: t, definition: d })
    if (uuid !== sessionUuid.value) return
    term.value = ''
    definition.value = ''
    showForm.value = false
    await load()
  } catch (e) {
    if (uuid === sessionUuid.value) error.value = apiErrorMessage(e)
  } finally {
    if (uuid === sessionUuid.value) saving.value = false
  }
}

async function remove(t: string): Promise<void> {
  const uuid = sessionUuid.value
  if (!uuid) return
  error.value = null
  try {
    await deleteInstruction(uuid, t)
    if (uuid !== sessionUuid.value) return
    await load()
  } catch (e) {
    if (uuid === sessionUuid.value) error.value = apiErrorMessage(e)
  }
}
</script>

<template>
  <div class="min-h-[250px] overflow-hidden rounded-5 border border-outline-gray-1 bg-surface-base shadow-sm">
    <div class="flex items-center justify-between border-b border-outline-gray-1 bg-surface-gray-1 px-4 py-3">
      <h3 class="text-sm font-semibold text-ink-gray-8">Custom Instructions</h3>
      <button
        type="button"
        class="inline-flex items-center gap-1 text-xs font-medium text-primary transition-colors hover:text-primary-7"
        @click="showForm = !showForm"
      >
        <Plus class="h-3.5 w-3.5" /> Add
      </button>
    </div>

    <div class="space-y-3 p-4">
      <p class="text-xs leading-relaxed text-ink-gray-5">
        Define business terms for the AI. These are added to the prompt and invalidate
        cached SQL when changed.
      </p>

      <!-- Add form -->
      <div v-if="showForm" class="space-y-2 rounded-4 border border-outline-gray-2 bg-surface-gray-1 p-3">
        <input
          v-model="term"
          type="text"
          placeholder="Term (e.g. active user)"
          class="w-full rounded-3 border border-outline-gray-2 bg-surface-base px-2.5 py-1.5 text-sm text-ink-gray-8 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:outline-none"
        />
        <textarea
          v-model="definition"
          rows="2"
          placeholder="Definition (e.g. logged in within 30 days AND spend > 10)"
          class="w-full resize-none rounded-3 border border-outline-gray-2 bg-surface-base px-2.5 py-1.5 text-sm text-ink-gray-8 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:outline-none"
        ></textarea>
        <div class="flex justify-end gap-2">
          <button
            type="button"
            class="rounded-3 border border-outline-gray-2 bg-surface-base px-3 py-1 text-xs text-ink-gray-7 shadow-sm hover:bg-surface-gray-2"
            @click="showForm = false"
          >
            Cancel
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded-3 bg-primary px-3 py-1 text-xs font-medium text-ink-white shadow-sm hover:bg-primary-7 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="saving || !term.trim() || !definition.trim()"
            @click="save"
          >
            <Loader2 v-if="saving" class="h-3 w-3 animate-spin" /> Save
          </button>
        </div>
      </div>

      <div v-if="error" class="inline-flex items-center gap-1 text-xs text-ink-red">
        <AlertCircle class="h-3.5 w-3.5" /> {{ error }}
      </div>

      <div v-if="loading" class="inline-flex items-center gap-1.5 text-xs text-ink-gray-4">
        <Loader2 class="h-3.5 w-3.5 animate-spin" /> Loading…
      </div>

      <!-- Empty state -->
      <div
        v-else-if="items.length === 0"
        class="rounded-4 border border-dashed border-outline-gray-2 py-6 text-center text-xs text-ink-gray-4"
      >
        No terms defined yet.
      </div>

      <!-- List -->
      <div
        v-for="item in items"
        v-else
        :key="item.term"
        class="group rounded-4 border border-outline-gray-1 bg-surface-gray-1 p-3"
      >
        <div class="mb-1 flex items-start justify-between gap-2">
          <span class="text-sm font-semibold text-ink-gray-8">{{ item.term }}</span>
          <button
            type="button"
            class="shrink-0 text-ink-gray-4 opacity-0 transition-opacity hover:text-ink-red group-hover:opacity-100"
            title="Delete term"
            @click="remove(item.term)"
          >
            <Trash2 class="h-4 w-4" />
          </button>
        </div>
        <p class="break-words font-mono text-xs text-ink-gray-6">{{ item.definition }}</p>
      </div>
    </div>
  </div>
</template>
