<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  Table,
  BarChart3,
  Database,
  CalendarClock,
  Settings,
  PanelLeft,
  PanelLeftClose,
  Undo2,
  Redo2,
} from '@lucide/vue'
import { useSession } from './composables/useSession'

const route = useRoute()
const collapsed = ref(false)

// Transform history lives on the shared session; the header Undo/Redo act on the
// loaded dataset regardless of the current route.
const { canUndo, canRedo, applying, undo, redo, restoreSession } = useSession()

// App is the always-mounted root (mounted exactly once), so this is the single place
// to rehydrate a persisted session after a page refresh — before any view renders it.
onMounted(() => {
  void restoreSession()
})

// Primary sections — real routes driven by vue-router.
const navItems = [
  { label: 'Table', icon: Table, to: '/table' },
  { label: 'Canvas', icon: BarChart3, to: '/canvas' },
  { label: 'Query Engine', icon: Database, to: '/query' },
]

// Roadmap surfaces — inert until their tasks land (kept visible so the plan stays legible).
const futureItems = [
  { label: 'Scheduled Runs', icon: CalendarClock },
  { label: 'Settings', icon: Settings },
]
</script>

<template>
  <div class="flex h-screen bg-surface-gray-1 font-sans text-ink-gray-8">
    <!-- Sidebar -->
    <aside
      class="flex flex-col border-r border-outline-gray-1 bg-surface-gray-1 transition-all duration-200"
      :class="collapsed ? 'w-16' : 'w-60'"
    >
      <!-- Brand -->
      <div class="flex h-16 shrink-0 items-center gap-2.5 border-b border-outline-gray-1 px-4">
        <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-4 bg-primary text-sm font-semibold text-ink-white shadow-sm">
          S
        </div>
        <span v-if="!collapsed" class="truncate text-base font-semibold text-ink-gray-9">Spencer</span>
      </div>

      <!-- Nav -->
      <nav class="flex-1 space-y-1 p-3">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          custom
          v-slot="{ isActive, href, navigate }"
        >
          <a
            :href="href"
            class="flex items-center gap-3 rounded-3 px-3 py-2 text-sm font-medium transition-colors"
            :class="isActive
              ? 'bg-surface-gray-3 text-ink-gray-9'
              : 'text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-8'"
            :title="collapsed ? item.label : undefined"
            @click="navigate"
          >
            <component :is="item.icon" class="h-4 w-4 shrink-0" />
            <span v-if="!collapsed" class="truncate">{{ item.label }}</span>
          </a>
        </RouterLink>

        <!-- Roadmap (inert; wiring lands in later tasks) -->
        <div class="mt-3 border-t border-outline-gray-1 pt-3">
          <span
            v-if="!collapsed"
            class="mb-1 block px-3 text-[11px] font-medium uppercase tracking-wide text-ink-gray-4"
          >
            Coming soon
          </span>
          <div
            v-for="item in futureItems"
            :key="item.label"
            class="flex cursor-not-allowed items-center gap-3 rounded-3 px-3 py-2 text-sm font-medium text-ink-gray-4"
            :title="collapsed ? item.label + ' (coming soon)' : undefined"
          >
            <component :is="item.icon" class="h-4 w-4 shrink-0" />
            <span v-if="!collapsed" class="truncate">{{ item.label }}</span>
          </div>
        </div>
      </nav>

      <!-- Collapse toggle -->
      <div class="border-t border-outline-gray-1 p-3">
        <button
          type="button"
          class="flex w-full items-center gap-3 rounded-3 px-3 py-2 text-sm font-medium text-ink-gray-6 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-8"
          :title="collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
          @click="collapsed = !collapsed"
        >
          <component :is="collapsed ? PanelLeft : PanelLeftClose" class="h-4 w-4 shrink-0" />
          <span v-if="!collapsed">Collapse</span>
        </button>
      </div>
    </aside>

    <!-- Main Content -->
    <main class="flex flex-1 flex-col overflow-hidden">
      <header class="flex h-16 shrink-0 items-center justify-between border-b border-outline-gray-1 bg-surface-base px-8">
        <h2 class="text-lg font-semibold text-ink-gray-9">{{ route.meta.title }}</h2>
        <div class="flex gap-2">
          <button
            type="button"
            :disabled="!canUndo || applying"
            class="inline-flex items-center gap-1.5 rounded-3 border border-outline-gray-2 bg-surface-base px-3 py-1.5 text-sm font-medium shadow-sm transition-colors"
            :class="(!canUndo || applying)
              ? 'cursor-not-allowed text-ink-gray-4'
              : 'text-ink-gray-7 hover:bg-surface-gray-2 hover:text-ink-gray-9'"
            title="Undo last transform"
            @click="undo"
          >
            <Undo2 class="h-4 w-4" /> Undo
          </button>
          <button
            type="button"
            :disabled="!canRedo || applying"
            class="inline-flex items-center gap-1.5 rounded-3 border border-outline-gray-2 bg-surface-base px-3 py-1.5 text-sm font-medium shadow-sm transition-colors"
            :class="(!canRedo || applying)
              ? 'cursor-not-allowed text-ink-gray-4'
              : 'text-ink-gray-7 hover:bg-surface-gray-2 hover:text-ink-gray-9'"
            title="Redo transform"
            @click="redo"
          >
            <Redo2 class="h-4 w-4" /> Redo
          </button>
        </div>
      </header>

      <div class="flex-1 overflow-auto p-8">
        <!-- keep-alive preserves each view's local state (e.g. the grid's scroll position)
             across navigation; session data already survives via the useSession singleton. -->
        <router-view v-slot="{ Component }">
          <keep-alive>
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </div>
    </main>
  </div>
</template>
