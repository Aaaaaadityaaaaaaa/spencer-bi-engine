<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Plus, Link2, Trash2, Database, AlertCircle } from '@lucide/vue'
import { useSession } from '../composables/useSession'
import { fetchRelationships, createRelationship, deleteRelationship, apiErrorMessage } from '../services/api'
import type { Relationship, RelationshipCreate } from '../types'
import { useToasts } from '../composables/useToast'

const { sessionUuid, tables } = useSession()
const { pushToast } = useToasts()

const relationships = ref<Relationship[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

// Form state
const isAdding = ref(false)
const form = ref<RelationshipCreate>({
  from_table: '',
  from_column: '',
  to_table: '',
  to_column: '',
  join_type: 'inner'
})

// Computed for dropdowns
const fromTableObj = computed(() => tables.value.find(t => t.table_name === form.value.from_table))
const toTableObj = computed(() => tables.value.find(t => t.table_name === form.value.to_table))

async function loadRels() {
  if (!sessionUuid.value) return
  loading.value = true
  try {
    relationships.value = await fetchRelationships(sessionUuid.value)
  } catch (e) {
    error.value = apiErrorMessage(e)
  } finally {
    loading.value = false
  }
}

watch(sessionUuid, () => {
  loadRels()
}, { immediate: true })

function resetForm() {
  form.value = { from_table: '', from_column: '', to_table: '', to_column: '', join_type: 'inner' }
  isAdding.value = false
}

async function handleCreate() {
  if (!sessionUuid.value) return
  try {
    const created = await createRelationship(sessionUuid.value, form.value)
    relationships.value.push(created)
    pushToast('Relationship created', 'success')
    resetForm()
  } catch (e) {
    pushToast(apiErrorMessage(e), 'error')
  }
}

async function handleDelete(id: string) {
  if (!sessionUuid.value) return
  try {
    await deleteRelationship(sessionUuid.value, id)
    relationships.value = relationships.value.filter(r => r.id !== id)
    pushToast('Relationship removed', 'success')
  } catch (e) {
    pushToast(apiErrorMessage(e), 'error')
  }
}
</script>

<template>
  <div class="h-full flex flex-col space-y-5 animate-fade-in-up">
    <div class="flex items-center justify-between rounded-5 border border-outline-gray-1 bg-surface-base px-5 py-4 shadow-sm">
      <div>
        <h2 class="text-lg font-semibold text-ink-gray-9">Data Model</h2>
        <p class="text-sm text-ink-gray-5">Define relationships between tables to power cross-table AI queries.</p>
      </div>
      <button v-if="!isAdding" @click="isAdding = true" class="btn btn-primary" :disabled="tables.length < 2">
        <Plus class="h-4 w-4" /> New Relationship
      </button>
    </div>
    
    <div v-if="tables.length < 2" class="rounded-5 border border-outline-gray-1 bg-amber-50 p-6 text-center text-amber-800">
      <AlertCircle class="mx-auto mb-2 h-8 w-8 opacity-50" />
      <h3 class="font-medium">You need at least two tables</h3>
      <p class="mt-1 text-sm opacity-80">Upload more files in the Table view to start building relationships.</p>
    </div>

    <!-- Add Form -->
    <div v-else-if="isAdding" class="rounded-5 border border-outline-gray-1 bg-surface-base p-6 shadow-sm">
      <h3 class="mb-4 font-semibold text-ink-gray-9">Create Relationship</h3>
      <div class="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-5">
        
        <div class="space-y-3 lg:col-span-2">
          <label class="block text-sm font-medium text-ink-gray-7">Table 1</label>
          <select v-model="form.from_table" class="input w-full">
            <option value="" disabled>Select a table...</option>
            <option v-for="t in tables" :key="t.table_name" :value="t.table_name">{{ t.table_name }}</option>
          </select>
          <select v-model="form.from_column" class="input w-full" :disabled="!form.from_table">
            <option value="" disabled>Select column...</option>
            <option v-for="c in fromTableObj?.columns" :key="c.name" :value="c.name">{{ c.name }}</option>
          </select>
        </div>
        
        <div class="flex flex-col items-center justify-center space-y-2 lg:col-span-1">
          <select v-model="form.join_type" class="input w-full text-center font-mono text-sm">
            <option value="inner">INNER JOIN</option>
            <option value="left">LEFT JOIN</option>
            <option value="right">RIGHT JOIN</option>
            <option value="full">FULL JOIN</option>
          </select>
          <Link2 class="h-6 w-6 text-ink-gray-4" />
        </div>
        
        <div class="space-y-3 lg:col-span-2">
          <label class="block text-sm font-medium text-ink-gray-7">Table 2</label>
          <select v-model="form.to_table" class="input w-full">
            <option value="" disabled>Select a table...</option>
            <option v-for="t in tables" :key="t.table_name" :value="t.table_name" :disabled="t.table_name === form.from_table">{{ t.table_name }}</option>
          </select>
          <select v-model="form.to_column" class="input w-full" :disabled="!form.to_table">
            <option value="" disabled>Select column...</option>
            <option v-for="c in toTableObj?.columns" :key="c.name" :value="c.name">{{ c.name }}</option>
          </select>
        </div>
        
      </div>
      
      <div class="mt-6 flex justify-end gap-3 border-t border-outline-gray-1 pt-4">
        <button @click="resetForm" class="btn btn-ghost">Cancel</button>
        <button 
          @click="handleCreate" 
          class="btn btn-primary"
          :disabled="!form.from_table || !form.from_column || !form.to_table || !form.to_column"
        >
          Save Relationship
        </button>
      </div>
    </div>

    <!-- List -->
    <div class="flex-1 rounded-5 border border-outline-gray-1 bg-surface-base shadow-sm">
      <div class="border-b border-outline-gray-1 bg-surface-gray-1 px-5 py-3">
        <h3 class="text-sm font-semibold text-ink-gray-8">Active Relationships</h3>
      </div>
      
      <div v-if="loading" class="p-8 text-center text-ink-gray-5">Loading...</div>
      <div v-else-if="relationships.length === 0" class="p-8 text-center text-ink-gray-5">
        No relationships defined yet.
      </div>
      <div v-else class="divide-y divide-outline-gray-1">
        <div v-for="rel in relationships" :key="rel.id" class="flex items-center justify-between p-4 hover:bg-surface-gray-1/50 transition-colors">
          <div class="flex items-center gap-6">
            <div class="flex flex-col min-w-0 flex-1">
              <span class="text-xs font-medium uppercase tracking-wider text-ink-gray-5">Table 1</span>
              <div class="mt-1 flex items-center gap-2 min-w-0">
                <Database class="h-4 w-4 shrink-0 text-primary" />
                <span class="font-medium text-ink-gray-9 truncate block max-w-[200px]" :title="rel.from_table">{{ rel.from_table }}</span>
                <span class="shrink-0 rounded bg-surface-gray-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-gray-6">{{ rel.from_column }}</span>
              </div>
            </div>
            
            <div class="flex flex-col items-center">
              <span class="rounded-full bg-primary-1 px-2.5 py-1 text-xs font-semibold text-primary">
                {{ rel.join_type.toUpperCase() }} JOIN
              </span>
              <div class="h-px w-16 bg-outline-gray-2 mt-2"></div>
            </div>
            
            <div class="flex flex-col min-w-0 flex-1">
              <span class="text-xs font-medium uppercase tracking-wider text-ink-gray-5">Table 2</span>
              <div class="mt-1 flex items-center gap-2 min-w-0">
                <Database class="h-4 w-4 shrink-0 text-primary" />
                <span class="font-medium text-ink-gray-9 truncate block max-w-[200px]" :title="rel.to_table">{{ rel.to_table }}</span>
                <span class="shrink-0 rounded bg-surface-gray-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-gray-6">{{ rel.to_column }}</span>
              </div>
            </div>
          </div>
          
          <button @click="handleDelete(rel.id)" class="btn btn-ghost text-ink-red hover:bg-red-50" title="Remove Relationship">
            <Trash2 class="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
