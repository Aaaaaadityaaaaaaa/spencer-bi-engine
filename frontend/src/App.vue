<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
  LogOut,
  X,
  Search,
  Keyboard,
} from '@lucide/vue'
import { useSession } from './composables/useSession'
import { useAuth } from './composables/useAuth'
import { useTileDrawer } from './composables/useTileDrawer'
import { useToasts } from './composables/useToast'
import { setOnUnauthorized } from './services/api'
import TableSwitcher from './components/TableSwitcher.vue'
import CommandPalette, { type Command } from './components/CommandPalette.vue'
import ToastHost from './components/ToastHost.vue'

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)
const paletteOpen = ref(false)
const cheatsheetOpen = ref(false)

// Sidebar collapse persists across reloads (Batch 1: habit-forming).
const COLLAPSE_KEY = 'spencer.sidebar.collapsed'
collapsed.value = localStorage.getItem(COLLAPSE_KEY) === '1'
watch(collapsed, (v) => localStorage.setItem(COLLAPSE_KEY, v ? '1' : '0'))

// Transform history lives on the shared session; the header Undo/Redo act on the
// loaded dataset regardless of the current route.
const { canUndo, canRedo, applying, undo, redo, restoreSession, sessionUuid } = useSession()
// tables / setActiveTable / addTable are consumed by the multi-table switcher (TableSwitcher.vue).

// Auth (TASK-027): the shell renders only when authenticated; /login shows bare.
const { isAuthenticated, user, logout } = useAuth()
const { pushToast } = useToasts()

// Per-visual settings drawer (Power BI–style): the selected tile teleports its editor into the
// host below. Imported here so the drawer chrome lives at the app root, outside the Canvas.
const { selectedTile, closeTileDrawer } = useTileDrawer()

// Breadcrumb: which dataset every action is currently targeting (Batch 1: information).
const activeTableLabel = computed(() => {
  const name = sessionUuid.value ? sessionUuid.value.slice(0, 8) : null
  return name ?? 'No table'
})

function goLogin(): void {
  if (router.currentRoute.value.path !== '/login') void router.replace({ path: '/login' })
}

function onLogout(): void {
  logout()
  goLogin()
}

function togglePalette(): void {
  paletteOpen.value = !paletteOpen.value
}

// Global keyboard shortcuts (Batch 1: habit-forming). Cmd/Ctrl-K -> palette,
// "?" -> cheatsheet (ignored while typing in an input).
function onGlobalKey(e: KeyboardEvent): void {
  const tag = (e.target as HTMLElement)?.tagName
  const typing = tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement)?.isContentEditable
  if (typing) return
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    togglePalette()
  } else if (e.key === '?' && !e.metaKey && !e.ctrlKey) {
    // "?" toggles the cheatsheet (advertised in the cheatsheet itself as a toggle).
    e.preventDefault()
    cheatsheetOpen.value = !cheatsheetOpen.value
  } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
    // ⌘Z / Ctrl+Z — advertised in the cheatsheet, so it has to actually work.
    e.preventDefault()
    runUndo()
  } else if ((e.metaKey || e.ctrlKey) && (e.key.toLowerCase() === 'z' && e.shiftKey || e.key.toLowerCase() === 'y')) {
    // ⌘⇧Z / Ctrl+Y
    e.preventDefault()
    runRedo()
  } else if (e.key === 'Escape' && cheatsheetOpen.value) {
    cheatsheetOpen.value = false
  }
}

// Header Undo/Redo route through here so the button, the shortcut and the command
// palette all give identical feedback (a silent no-op is a UX dead end).
function runUndo(): void {
  if (!canUndo.value) { pushToast('Nothing to undo', 'info'); return }
  undo()
  pushToast('Undid last transform', 'success')
}

function runRedo(): void {
  if (!canRedo.value) { pushToast('Nothing to redo', 'info'); return }
  redo()
  pushToast('Redid transform', 'success')
}

// App is the always-mounted root (mounted exactly once), so this is the single place
// to rehydrate a persisted session after a page refresh — before any view renders it.
onMounted(() => {
  // A guarded call returning 401 mid-session (token expired / cleared server-side) logs
  // us out; goLogin handles the redirect. (401s from /auth/* self-handle — see api.ts.)
  setOnUnauthorized(() => {
    logout()
    goLogin()
  })
  window.addEventListener('keydown', onGlobalKey)
  // main.ts already rehydrated the token synchronously, so restore only fires for an
  // authenticated returning user; the empty state shows the upload screen otherwise.
  if (isAuthenticated.value) void restoreSession()
})
onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKey))

// React to auth flips that don't originate from a navigation:
//  - login (false -> true): rehydrate that user's persisted session, if any.
//  - involuntary logout (true -> false, e.g. boot token-revalidation 401): bounce to /login.
watch(isAuthenticated, (authed) => {
  if (authed) void restoreSession()
  else goLogin()
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

// Command palette registry (Batch 1). Each action is a plain callback so this stays
// decoupled from view internals; add new commands here as features land.
const commands = computed<Command[]>(() => [
  { id: 'nav-table', label: 'Go to Table', group: 'Navigate', hint: 'G T', run: () => router.push('/table') },
  { id: 'nav-canvas', label: 'Go to Canvas', group: 'Navigate', hint: 'G C', run: () => router.push('/canvas') },
  { id: 'nav-query', label: 'Go to Query Engine', group: 'Navigate', hint: 'G Q', run: () => router.push('/query') },
  {
    id: 'act-undo',
    label: 'Undo last transform',
    group: 'Actions',
    hint: '⌘Z',
    run: runUndo,
  },
  {
    id: 'act-redo',
    label: 'Redo transform',
    group: 'Actions',
    hint: '⌘⇧Z',
    run: runRedo,
  },
  { id: 'act-search', label: 'Open command palette', group: 'Actions', hint: '⌘K', run: () => (paletteOpen.value = true) },
])
</script>

<template>
  <div v-if="isAuthenticated" class="flex h-screen bg-surface-gray-1 font-sans text-ink-gray-8 p-0 sm:p-2 md:p-3 overflow-hidden bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-primary-2/30 via-surface-gray-1 to-surface-gray-2 relative">
    
    <!-- Decorative subtle glows for the mesh gradient -->
    <div class="pointer-events-none absolute -top-40 -right-40 h-[500px] w-[500px] rounded-full bg-primary-3/20 blur-[100px]"></div>
    <div class="pointer-events-none absolute -bottom-40 -left-40 h-[500px] w-[500px] rounded-full bg-primary-2/20 blur-[100px]"></div>
    <!-- Sidebar -->
    <aside
      class="flex flex-col bg-transparent transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]"
      :class="collapsed ? 'w-16' : 'w-60'"
    >
      <!-- Brand -->
      <div class="flex h-16 shrink-0 items-center gap-2.5 px-4">
        <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-3 bg-gradient-to-br from-primary-5 to-primary-7 text-sm font-semibold text-white shadow-sm ring-1 ring-white/20">
          S
        </div>
        <span v-if="!collapsed" class="truncate text-base font-semibold tracking-tight text-ink-gray-9">Spencer</span>
      </div>

      <!-- Nav -->
      <nav class="flex-1 space-y-1.5 p-3">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          custom
          v-slot="{ isActive, href, navigate }"
        >
          <a
            :href="href"
            class="group relative flex items-center gap-3 rounded-3 px-3 py-2 text-sm font-medium transition-all duration-200 ease-out hover:bg-white/60"
            :class="isActive
              ? 'bg-white text-primary-7 shadow-sm ring-1 ring-outline-gray-2/50'
              : 'text-ink-gray-6'"
            :title="collapsed ? item.label : undefined"
            @click="navigate"
          >
            <!-- Animated background pill for active state -->
            <div v-if="isActive" class="absolute inset-0 rounded-3 bg-white shadow-sm ring-1 ring-outline-gray-2/50 -z-10"></div>
            
            <component :is="item.icon" class="h-4 w-4 shrink-0 transition-transform duration-200 group-hover:scale-110" />
            <span v-if="!collapsed" class="truncate relative z-10">{{ item.label }}</span>
          </a>
        </RouterLink>

        <!-- Roadmap -->
        <div class="mt-4 pt-4">
          <span
            v-if="!collapsed"
            class="mb-2 block px-3 text-[10px] font-semibold uppercase tracking-wider text-ink-gray-4"
          >
            Coming soon
          </span>
          <div
            v-for="item in futureItems"
            :key="item.label"
            class="flex cursor-not-allowed items-center gap-3 rounded-3 px-3 py-2 text-sm font-medium text-ink-gray-4 transition-colors"
            :title="collapsed ? item.label : undefined"
          >
            <component :is="item.icon" class="h-4 w-4 shrink-0 opacity-50" />
            <span v-if="!collapsed" class="truncate">{{ item.label }}</span>
          </div>
        </div>
      </nav>

      <!-- Sidebar footer -->
      <div class="mt-auto border-t border-outline-gray-2/40 p-3 flex flex-col gap-1.5">
        <button
          type="button"
          class="flex items-center gap-3 rounded-3 px-3 py-2 text-sm font-medium text-ink-gray-5 transition-all duration-200 hover:bg-white/60 hover:text-ink-gray-8"
          :title="collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
          @click="collapsed = !collapsed"
        >
          <PanelLeftClose v-if="!collapsed" class="h-4 w-4 shrink-0 transition-transform duration-200 hover:-translate-x-0.5" />
          <PanelLeft v-else class="h-4 w-4 shrink-0 transition-transform duration-200 hover:translate-x-0.5" />
          <span v-if="!collapsed" class="truncate">Collapse</span>
        </button>
        
        <div v-if="!collapsed" class="flex items-center justify-between rounded-3 px-3 py-2 text-sm font-medium">
          <div class="flex items-center gap-2 truncate">
            <div class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-gray-3 text-[9px] font-bold text-ink-gray-6 ring-1 ring-outline-gray-2">
              {{ user?.email?.charAt(0).toUpperCase() || 'U' }}
            </div>
            <span class="truncate text-ink-gray-7">{{ user?.email }}</span>
          </div>
          <button
            type="button"
            class="shrink-0 rounded-2 p-1 text-ink-gray-4 transition-colors hover:bg-white hover:text-ink-red hover:shadow-sm"
            title="Sign out"
            @click="onLogout"
          >
            <LogOut class="h-3.5 w-3.5" />
          </button>
        </div>
        <button
          v-if="collapsed"
          type="button"
          class="flex w-full items-center justify-center rounded-3 px-3 py-2 text-ink-gray-5 transition-colors hover:bg-white/60 hover:text-ink-red"
          title="Sign out"
          @click="onLogout"
        >
          <LogOut class="h-4 w-4 shrink-0" />
        </button>
      </div>
    </aside>

    <!-- Main Content (Floating Inset Panel) -->
    <main class="flex flex-1 flex-col overflow-hidden bg-surface-base sm:rounded-4 border-l sm:border border-outline-gray-2/60 shadow-[0_8px_30px_rgb(0,0,0,0.04)] relative z-10 transition-all duration-300 animate-fade-in-up">
      <header class="flex h-14 shrink-0 items-center justify-between border-b border-outline-gray-1 bg-surface-base/80 backdrop-blur-md px-5 z-20 sticky top-0">
        <div class="flex items-center gap-3">
          <h2 class="text-base font-semibold tracking-tight text-ink-gray-9">{{ route.meta.title }}</h2>
          <span
            v-if="sessionUuid"
            class="hidden items-center gap-1.5 rounded-2 bg-surface-gray-1 px-2 py-0.5 text-xs font-medium text-ink-gray-6 sm:inline-flex ring-1 ring-outline-gray-2/50"
            title="Active table"
          >
            <span class="h-1.5 w-1.5 rounded-full bg-primary-5 animate-pulse"></span>
            {{ activeTableLabel }}
          </span>
        </div>
        <div class="flex items-center gap-1">
          <button
            type="button"
            class="flex items-center gap-1.5 rounded-3 px-2 py-1.5 text-sm font-medium text-ink-gray-5 hover:bg-surface-gray-1 hover:text-ink-gray-8 transition-all"
            title="Search commands  (⌘K)"
            @click="togglePalette"
          >
            <Search class="h-4 w-4" />
            <span class="hidden md:inline">Search</span>
            <kbd class="ml-1 hidden rounded-1 border border-outline-gray-2 bg-white px-1 text-[10px] text-ink-gray-4 md:inline shadow-sm">⌘K</kbd>
          </button>
          
          <div class="w-px h-4 bg-outline-gray-2 mx-1 hidden sm:block"></div>

          <button
            type="button"
            class="rounded-3 p-1.5 text-ink-gray-5 hover:bg-surface-gray-1 hover:text-ink-gray-8 transition-all"
            title="Keyboard shortcuts  (?)"
            aria-label="Keyboard shortcuts"
            @click="cheatsheetOpen = !cheatsheetOpen"
          >
            <Keyboard class="h-4 w-4" />
          </button>
          
          <button
            type="button"
            :disabled="!canUndo || applying"
            class="rounded-3 p-1.5 transition-all"
            :class="(!canUndo || applying)
              ? 'cursor-not-allowed text-ink-gray-3'
              : 'text-ink-gray-6 hover:bg-surface-gray-1 hover:text-ink-gray-9'"
            title="Undo last transform  (⌘Z)"
            @click="runUndo"
          >
            <Undo2 class="h-4 w-4" />
          </button>
          <button
            type="button"
            :disabled="!canRedo || applying"
            class="rounded-3 p-1.5 transition-all"
            :class="(!canRedo || applying)
              ? 'cursor-not-allowed text-ink-gray-3'
              : 'text-ink-gray-6 hover:bg-surface-gray-1 hover:text-ink-gray-9'"
            title="Redo transform  (⇧⌘Z)"
            @click="runRedo"
          >
            <Redo2 class="h-4 w-4" />
          </button>
        </div>
      </header>

      <!-- Multi-table switcher -->
      <TableSwitcher />

       <div class="flex-1 overflow-auto p-4 sm:p-6 bg-surface-gray-1/30">
        <router-view v-slot="{ Component }">
          <Transition name="fade" mode="out-in">
            <keep-alive>
              <component :is="Component" :key="route.path" />
            </keep-alive>
          </Transition>
        </router-view>
      </div>
    </main>

    <!-- Tile Drawer -->
    <Transition name="fade">
      <div
        v-if="selectedTile"
        class="js-export-exclude fixed inset-0 z-40 bg-transparent"
        @click="closeTileDrawer()"
      ></div>
    </Transition>
    <aside
      class="js-export-exclude fixed top-0 z-50 flex h-full w-80 max-w-[90vw] flex-col border-l border-outline-gray-2 bg-surface-base shadow-2xl transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]"
      :class="selectedTile ? 'right-0' : '-right-80'"
      aria-label="Tile settings"
    >
      <div class="flex items-center justify-between border-b border-outline-gray-1 px-4 py-3 bg-surface-base/50">
        <h3 class="text-sm font-semibold tracking-tight text-ink-gray-9">
          {{ selectedTile?.kind === 'kpi' ? 'Card Settings' : 'Chart Settings' }}
        </h3>
        <button
          type="button"
          class="rounded-full p-1 text-ink-gray-5 transition-all hover:bg-surface-gray-2 hover:text-ink-gray-9 hover:rotate-90"
          title="Close"
          @click="closeTileDrawer()"
        >
          <X class="h-4 w-4" />
        </button>
      </div>
      <div class="flex-1 overflow-y-auto p-4">
        <div id="tile-settings-drawer-body"></div>
      </div>
    </aside>

    <CommandPalette v-model:open="paletteOpen" :commands="commands" />

    <Transition name="fade">
      <div
        v-if="cheatsheetOpen"
        class="fixed inset-0 z-[60] flex items-center justify-center bg-surface-scrim backdrop-blur-sm px-4"
        @click.self="cheatsheetOpen = false"
      >
        <div class="w-full max-w-sm rounded-4 border border-outline-gray-2 bg-surface-base p-6 shadow-xl animate-scale-in">
          <div class="mb-4 flex items-center justify-between">
            <h3 class="text-base font-semibold tracking-tight text-ink-gray-9">Keyboard Shortcuts</h3>
            <button
              type="button"
              class="rounded-full p-1 text-ink-gray-5 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-9"
              @click="cheatsheetOpen = false"
            >
              <X class="h-4 w-4" />
            </button>
          </div>
          <ul class="space-y-2 text-sm text-ink-gray-6">
            <li class="flex items-center justify-between border-b border-outline-gray-1/50 pb-2">
              <span>Command palette</span>
              <kbd class="rounded-2 border border-outline-gray-2 bg-surface-gray-1 px-1.5 py-0.5 text-[10px] font-semibold text-ink-gray-7 shadow-sm">⌘ K</kbd>
            </li>
            <li class="flex items-center justify-between border-b border-outline-gray-1/50 pb-2">
              <span>Undo transform</span>
              <kbd class="rounded-2 border border-outline-gray-2 bg-surface-gray-1 px-1.5 py-0.5 text-[10px] font-semibold text-ink-gray-7 shadow-sm">⌘ Z</kbd>
            </li>
            <li class="flex items-center justify-between border-b border-outline-gray-1/50 pb-2">
              <span>Redo transform</span>
              <kbd class="rounded-2 border border-outline-gray-2 bg-surface-gray-1 px-1.5 py-0.5 text-[10px] font-semibold text-ink-gray-7 shadow-sm">⇧ ⌘ Z</kbd>
            </li>
            <li class="flex items-center justify-between">
              <span>Toggle shortcuts</span>
              <kbd class="rounded-2 border border-outline-gray-2 bg-surface-gray-1 px-1.5 py-0.5 text-[10px] font-semibold text-ink-gray-7 shadow-sm">?</kbd>
            </li>
          </ul>
        </div>
      </div>
    </Transition>
  </div>

  <router-view v-else />
  <ToastHost />
</template>
