<script setup lang="ts">
// Table section = the data-prep workspace: upload bar (collapses once loaded),
// the transform ribbon, the virtualized grid (with per-column ⋮ menus), one shared
// OpDialog, and the read-only column-profile drawer. Ribbon buttons and column menus
// funnel an OpRequest into `activeOp` (the dialog); the ⋮ "Profile column" entry sets
// `profileColumn` (the drawer). All state is the useSession singleton.
import { ref } from 'vue'
import UploadDropzone from '../components/UploadDropzone.vue'
import SuggestedQuestions from '../components/SuggestedQuestions.vue'
import DataQualityPanel from '../components/DataQualityPanel.vue'
import CleaningToolbar from '../components/CleaningToolbar.vue'
import DataGrid from '../components/DataGrid.vue'
import OpDialog from '../components/OpDialog.vue'
import ColumnProfilePanel from '../components/ColumnProfilePanel.vue'
import { useSession } from '../composables/useSession'
import type { OpRequest } from '../types'

const { sessionUuid } = useSession()
const activeOp = ref<OpRequest | null>(null)
const profileColumn = ref<string | null>(null)

function openOp(req: OpRequest): void {
  activeOp.value = req
}
function closeOp(): void {
  activeOp.value = null
}
function openProfile(column: string): void {
  profileColumn.value = column
}
function closeProfile(): void {
  profileColumn.value = null
}
</script>

<template>
  <div class="space-y-5">
    <UploadDropzone />
    <SuggestedQuestions v-if="sessionUuid" />
    <DataQualityPanel v-if="sessionUuid" @fix="openOp" @profile="openProfile" />
    <CleaningToolbar v-if="sessionUuid" @open="openOp" />
    <DataGrid @column-op="openOp" @profile-column="openProfile" />
    <OpDialog :request="activeOp" @close="closeOp" />
    <ColumnProfilePanel :column="profileColumn" @close="closeProfile" />
  </div>
</template>
