/// <reference types="vite/client" />

// Augments Vite's env typing with the one custom var this app reads.
interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
