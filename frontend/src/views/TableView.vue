<script setup lang="ts">
// Table section = the data-prep workspace: upload bar (collapses once loaded),
// the Data Quality card, a single Clean ▾ menu (Batch 3 / Table — replaces the
// 15-button ribbon), the virtualized grid (with per-column ⋮ menus), one shared
// OpDialog, and the read-only column-profile drawer. The menu and column menus
// funnel an OpRequest into `activeOp` (the dialog); the ⋮ "Profile column" entry
// sets `profileColumn` (the drawer). All state is the useSession singleton.
import { ref } from 'vue'
import { Loader2 } from '@lucide/vue'
import UploadDropzone from '../components/UploadDropzone.vue'
import DataQualityPanel from '../components/DataQualityPanel.vue'
import CleaningToolbar from '../components/CleaningToolbar.vue'
import DataGrid from '../components/DataGrid.vue'
import OpDialog from '../components/OpDialog.vue'
import ColumnProfilePanel from '../components/ColumnProfilePanel.vue'
import { useSession } from '../composables/useSession'
import type { OpRequest } from '../types'

const { sessionUuid, restoring } = useSession()
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
    <!-- Restoring a persisted session on page load: hold the upload screen back so it
         doesn't flash before the rehydrated table lands (see useSession.restoreSession). -->
    <div
      v-if="restoring"
      class="flex items-center justify-center gap-2 rounded-5 border border-outline-gray-1 bg-surface-base py-16 text-sm text-ink-gray-5 shadow-sm"
    >
      <Loader2 class="h-4 w-4 animate-spin text-primary" /> Restoring your session…
    </div>
    <template v-else>
      <UploadDropzone />
      <!-- The dedicated Data Quality card, and the single Clean menu -->
      <DataQualityPanel v-if="sessionUuid" @fix="openOp" @profile="openProfile" />
      <CleaningToolbar v-if="sessionUuid" @open="openOp" />
      <DataGrid v-if="sessionUuid" @column-op="openOp" @profile-column="openProfile" />
    </template>
    <Transition name="modal">
      <OpDialog v-if="activeOp" :request="activeOp" @close="closeOp" />
    </Transition>
    <ColumnProfilePanel :column="profileColumn" @close="closeProfile" />
  </div>
</template>
