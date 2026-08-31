import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Dev-only override: route Vite's dep-optimization cache to a fresh directory
// so it builds from scratch instead of trying to clear the stale node_modules/.vite
// cache (which the safe-delete guard blocks). Additive — original vite.config.ts
// is untouched.
export default defineConfig({
  plugins: [vue()],
  cacheDir: 'node_modules/.vite-run',
})
