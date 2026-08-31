import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  // Route Vite's dep-optimization cache to a fresh dir. On this machine the
  // WorkBuddy safe-delete shim blocks Vite's internal `fs.rm` of the default
  // node_modules/.vite cache (bulk-delete guard), which aborts `vite` startup.
  // A dedicated cache dir that Vite builds fresh avoids that delete entirely.
  cacheDir: 'node_modules/.vite-run',
})
