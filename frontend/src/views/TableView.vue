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
import AppliedStepsPanel from '../components/AppliedStepsPanel.vue'
import { useSession } from '../composables/useSession'
import type { OpRequest } from '../types'

const { sessionUuid, restoring, showAppliedSteps } = useSession()
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
  <div class="space-y-5 animate-fade-in-up">
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
      <div v-if="sessionUuid" class="flex items-start gap-5 transition-all duration-300">
        <div class="flex-1 space-y-5 min-w-0 overflow-hidden">
          <!-- The dedicated Data Quality card, and the single Clean menu -->
          <DataQualityPanel @fix="openOp" @profile="openProfile" />
          <CleaningToolbar @open="openOp" />
          <DataGrid @column-op="openOp" @profile-column="openProfile" />
        </div>
        <Transition
          enter-active-class="transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]"
          enter-from-class="opacity-0 translate-x-8"
          enter-to-class="opacity-100 translate-x-0"
          leave-active-class="transition-all duration-200 ease-in"
          leave-from-class="opacity-100 translate-x-0"
          leave-to-class="opacity-0 translate-x-8"
        >
          <div v-show="showAppliedSteps" class="w-64 shrink-0 self-stretch">
            <AppliedStepsPanel />
          </div>
        </Transition>
      </div>
    </template>
    <Transition name="modal">
      <OpDialog v-if="activeOp" :request="activeOp" @close="closeOp" />
    </Transition>
    <ColumnProfilePanel :column="profileColumn" @close="closeProfile" />
  </div>
</template>
