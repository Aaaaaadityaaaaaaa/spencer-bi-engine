<script setup lang="ts">
// Table section: upload (schema pills render inside the dropzone) + the virtualized grid.
// Both components read/write the shared `useSession` singleton, so no props are threaded here.
import UploadDropzone from '../components/UploadDropzone.vue'
import DataGrid from '../components/DataGrid.vue'
</script>

<template>
  <div class="space-y-8">
    <UploadDropzone />
    <DataGrid />
  </div>
</template>
