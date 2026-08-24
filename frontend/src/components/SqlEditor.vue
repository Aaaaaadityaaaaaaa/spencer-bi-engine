<script setup lang="ts">
import { ref, computed, toRef } from 'vue'
import { useCodeMirror } from '../composables/useCodeMirror'
import type { CodeMirrorSchema } from '../composables/useCodeMirror'
import type { ColumnMeta } from '../types'

const props = defineProps<{
  sql: string
  readOnly?: boolean
  tableName?: string | null
  columns?: ColumnMeta[]
}>()
const emit = defineEmits<{ 'update:sql': [value: string]; run: [] }>()

const host = ref<HTMLElement | null>(null)
const doc = computed<string>({ get: () => props.sql, set: (v) => emit('update:sql', v) })
const readOnly = toRef(() => props.readOnly ?? false)
// The session table + columns, fed to CodeMirror for FROM/column autocomplete.
const schema = computed<CodeMirrorSchema>(() => ({
  table: props.tableName ?? null,
  columns: (props.columns ?? []).map((c) => c.name),
}))

const cm = useCodeMirror(host, doc, { onRun: () => emit('run'), readOnly, schema })

// Exposed so the parent's schema chips can drop a name straight into the query.
defineExpose({ insert: cm.insert })
</script>

<template>
  <div ref="host" class="h-[220px] overflow-hidden rounded-4 border border-outline-gray-2 bg-surface-base"></div>
</template>
