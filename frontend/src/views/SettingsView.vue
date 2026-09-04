<template>
  <div class="flex h-full flex-col bg-surface-gray-1">
    <!-- Header -->
    <header class="flex h-14 shrink-0 items-center justify-between border-b border-outline-gray-2 bg-surface-base px-6">
      <div class="flex items-center gap-3">
        <h1 class="text-base font-semibold tracking-tight text-ink-gray-9">Settings</h1>
      </div>
    </header>

    <!-- Main Content -->
    <div class="flex flex-1 overflow-hidden">
      <!-- Settings Sidebar -->
      <nav class="w-64 shrink-0 border-r border-outline-gray-2 bg-surface-gray-1/50 p-4 space-y-1">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          type="button"
          @click="activeTab = tab.id"
          class="flex w-full items-center gap-3 rounded-2 px-3 py-2 text-sm font-medium transition-colors"
          :class="activeTab === tab.id 
            ? 'bg-surface-base text-primary-7 shadow-sm ring-1 ring-outline-gray-2/50' 
            : 'text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-8'"
        >
          <component :is="tab.icon" class="h-4 w-4 shrink-0" />
          {{ tab.label }}
        </button>
      </nav>

      <!-- Tab Content -->
      <main class="flex-1 overflow-y-auto p-8 relative">
        <div class="mx-auto max-w-3xl space-y-8 pb-12">
          
          <!-- Appearance Tab -->
          <section v-if="activeTab === 'appearance'" class="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
            <div>
              <h2 class="text-lg font-semibold tracking-tight text-ink-gray-9">General / Appearance</h2>
              <p class="text-sm text-ink-gray-5">Customize the look and feel of your workspace.</p>
            </div>
            
            <div class="rounded-3 border border-outline-gray-2 bg-surface-base p-5 shadow-sm space-y-4">
              <h3 class="text-sm font-semibold text-ink-gray-9">Theme Preferences</h3>
              <div class="grid grid-cols-2 sm:grid-cols-3 gap-4">
                <button type="button" @click="setTheme('light')" class="flex flex-col items-center gap-2 rounded-3 border-2 p-4 transition-all"
                  :class="currentTheme !== 'dark' ? 'border-primary bg-surface-gray-1 ring-2 ring-primary/20' : 'border-outline-gray-2 bg-surface-base hover:bg-surface-gray-1'">
                  <div class="h-16 w-full rounded-2 border border-outline-gray-2 bg-white shadow-sm flex items-center justify-center text-xs font-bold text-zinc-900">Aa</div>
                  <span class="text-xs font-semibold" :class="currentTheme !== 'dark' ? 'text-primary' : 'text-ink-gray-6'">Light Mode</span>
                </button>
                <button type="button" @click="setTheme('dark')" class="flex flex-col items-center gap-2 rounded-3 border-2 p-4 transition-all"
                  :class="currentTheme === 'dark' ? 'border-primary bg-surface-gray-1 ring-2 ring-primary/20' : 'border-outline-gray-2 bg-surface-base hover:bg-surface-gray-1'">
                  <div class="h-16 w-full rounded-2 border border-outline-gray-2 bg-zinc-950 shadow-sm flex items-center justify-center text-xs font-bold text-zinc-100">Aa</div>
                  <span class="text-xs font-semibold" :class="currentTheme === 'dark' ? 'text-primary' : 'text-ink-gray-6'">Dark Mode</span>
                </button>
              </div>
            </div>
            
            <div class="rounded-3 border border-outline-gray-2 bg-surface-base p-5 shadow-sm space-y-5">
              <div>
                <h3 class="text-sm font-semibold text-ink-gray-9 mb-1">Global Chart Palette</h3>
                <p class="text-[11px] text-ink-gray-5 mb-4">Default color array applied to categorical charts.</p>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <button v-for="p in palettes" :key="p.id" type="button" 
                    @click="dashboardSettings.paletteId = p.id"
                    class="flex flex-col items-start gap-2 rounded-2 border p-3 transition-all text-left"
                    :class="((dashboardSettings.paletteId || 'default') === p.id) ? 'border-primary bg-primary-1/30 shadow-sm ring-1 ring-primary/30' : 'border-outline-gray-2 hover:bg-surface-gray-1'">
                    <span class="text-xs font-semibold" :class="((dashboardSettings.paletteId || 'default') === p.id) ? 'text-primary-7' : 'text-ink-gray-8'">{{ p.label }}</span>
                    <div class="flex gap-1 overflow-hidden rounded-1">
                      <div v-for="color in p.colors.slice(0, 8)" :key="color" class="h-4 w-4" :style="{ backgroundColor: color }"></div>
                    </div>
                  </button>
                </div>
              </div>

              <div class="pt-4 border-t border-outline-gray-2">
                <h3 class="text-sm font-semibold text-ink-gray-9 mb-1">Accent Color</h3>
                <p class="text-[11px] text-ink-gray-5 mb-3">Fallback color for single-series visuals.</p>
                <div class="flex items-center gap-3">
                  <input type="color" :value="swatch" @input="dashboardSettings.accent = ($event.target as HTMLInputElement).value" class="h-8 w-12 cursor-pointer rounded-2 border border-outline-gray-2 bg-transparent" />
                  <input type="text" v-model="hexText" placeholder="#hex / blank = brand" class="w-40 rounded-2 border border-outline-gray-2 bg-surface-base px-3 py-1.5 text-xs text-ink-gray-8" />
                  <button v-if="dashboardSettings.accent && dashboardSettings.accent !== '#000000'" type="button" class="text-[11px] text-ink-gray-5 underline-offset-2 hover:text-primary hover:underline" @click="dashboardSettings.accent = '#000000'">Reset to brand default</button>
                </div>
              </div>
            </div>

            <div class="rounded-3 border border-outline-gray-2 bg-surface-base p-5 shadow-sm space-y-4">
              <h3 class="text-sm font-semibold text-ink-gray-9">Number Formatting</h3>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-6">
                <div class="space-y-3">
                  <div class="flex items-center justify-between gap-3">
                    <label class="text-xs text-ink-gray-7">Decimal places</label>
                    <select v-model.number="dashboardSettings.decimalPlaces" class="rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-1 text-xs text-ink-gray-8">
                      <option v-for="d in [0, 1, 2, 3, 4]" :key="d" :value="d">{{ d }}</option>
                    </select>
                  </div>
                  <label class="flex items-center justify-between gap-3 cursor-pointer">
                    <span class="text-xs text-ink-gray-7">Thousands separator</span>
                    <input type="checkbox" v-model="dashboardSettings.thousands" class="h-4 w-4 accent-primary" />
                  </label>
                  <label class="flex items-center justify-between gap-3 cursor-pointer">
                    <span class="text-xs text-ink-gray-7">Compact (K / M / B)</span>
                    <input type="checkbox" v-model="dashboardSettings.compact" class="h-4 w-4 accent-primary" />
                  </label>
                </div>
                <div class="rounded-2 bg-surface-gray-1 p-4 border border-outline-gray-2 flex flex-col justify-center">
                  <span class="text-[10px] uppercase font-bold text-ink-gray-4 mb-1">Preview</span>
                  <span class="text-2xl font-semibold text-ink-gray-9">{{ formatNumber(1234567.891) }}</span>
                </div>
              </div>
            </div>
            
            <div class="rounded-3 border border-outline-gray-2 bg-surface-base p-5 shadow-sm">
              <h3 class="text-sm font-semibold text-ink-gray-9 mb-3">Charts</h3>
              <label class="flex items-center justify-between gap-3 cursor-pointer">
                <span class="text-xs text-ink-gray-7">Show values on charts by default</span>
                <input type="checkbox" v-model="dashboardSettings.showValues" class="h-4 w-4 accent-primary" />
              </label>
            </div>
          </section>

          <!-- Account Tab -->
          <section v-if="activeTab === 'account'" class="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
            <div>
              <h2 class="text-lg font-semibold tracking-tight text-ink-gray-9">Account & Security</h2>
              <p class="text-sm text-ink-gray-5">Manage your personal profile and authentication.</p>
            </div>
            
            <div class="rounded-3 border border-outline-gray-2 bg-surface-base p-5 shadow-sm flex items-center justify-between">
              <div>
                <h3 class="text-sm font-semibold text-ink-gray-9 mb-1">{{ user?.email || 'user@example.com' }}</h3>
                <p class="text-xs text-ink-gray-5">Role: <span class="font-semibold text-primary">{{ user?.is_admin ? 'Admin' : 'User' }}</span></p>
              </div>
              <div class="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary-1 text-lg font-bold text-primary-7 ring-2 ring-primary/20">
                {{ user?.email?.charAt(0).toUpperCase() || 'U' }}
              </div>
            </div>

            <div class="rounded-3 border border-outline-gray-2 bg-surface-base p-5 shadow-sm space-y-4">
              <h3 class="text-sm font-semibold text-ink-gray-9 mb-2">Change Password</h3>
              <form @submit.prevent="runChangePassword" class="space-y-4 max-w-sm">
                <div>
                  <label class="block text-[11px] font-bold uppercase tracking-wider text-ink-gray-5 mb-1">Current Password</label>
                  <input type="password" v-model="passwords.current" class="input w-full" required />
                </div>
                <div>
                  <label class="block text-[11px] font-bold uppercase tracking-wider text-ink-gray-5 mb-1">New Password</label>
                  <input type="password" v-model="passwords.new" class="input w-full" required />
                </div>
                <div>
                  <label class="block text-[11px] font-bold uppercase tracking-wider text-ink-gray-5 mb-1">Confirm New Password</label>
                  <input type="password" v-model="passwords.confirm" class="input w-full" required />
                </div>
                <button type="submit" :disabled="isChangingPassword" class="btn btn-primary w-full">
                  <Loader2 v-if="isChangingPassword" class="h-4 w-4 animate-spin mr-2" />
                  Update Password
                </button>
              </form>
            </div>

            <div class="rounded-3 border border-red-200 bg-red-50/50 p-5 shadow-sm">
              <h3 class="text-sm font-semibold text-red-900 mb-1">Sign Out</h3>
              <p class="text-xs text-red-700/80 mb-4">Log out of your current session on this device.</p>
              <button @click="logout" type="button" class="rounded-2 bg-red-600 px-4 py-2 text-xs font-bold text-white hover:bg-red-700 shadow-sm transition-colors">
                Sign Out
              </button>
            </div>
          </section>

          <!-- AI Tab -->
          <section v-if="activeTab === 'ai'" class="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
            <div>
              <h2 class="text-lg font-semibold tracking-tight text-ink-gray-9">AI & Intelligence</h2>
              <p class="text-sm text-ink-gray-5">View active model configuration and business dictionary.</p>
            </div>
            
            <div class="rounded-3 border border-outline-gray-2 bg-surface-base p-5 shadow-sm space-y-4">
              <h3 class="text-sm font-semibold text-ink-gray-9 mb-2">Active LLM Configuration</h3>
              <div v-if="aiConfig" class="grid grid-cols-2 gap-4">
                <div class="rounded-2 bg-surface-gray-1 p-3 border border-outline-gray-2">
                  <span class="text-[10px] uppercase font-bold text-ink-gray-5 block mb-1">Provider</span>
                  <span class="text-sm font-semibold text-ink-gray-9">{{ aiConfig.provider }}</span>
                </div>
                <div class="rounded-2 bg-surface-gray-1 p-3 border border-outline-gray-2">
                  <span class="text-[10px] uppercase font-bold text-ink-gray-5 block mb-1">Model</span>
                  <span class="text-sm font-semibold text-ink-gray-9 font-mono">{{ aiConfig.model }}</span>
                </div>
                <div class="rounded-2 bg-surface-gray-1 p-3 border border-outline-gray-2 col-span-2">
                  <span class="text-[10px] uppercase font-bold text-ink-gray-5 block mb-1">Reasoning Effort</span>
                  <span class="text-sm font-semibold text-ink-gray-9 capitalize">{{ aiConfig.reasoning_effort || 'Default' }}</span>
                </div>
              </div>
              <div v-else class="text-xs text-ink-gray-5 flex items-center gap-2">
                <Loader2 class="h-3 w-3 animate-spin" /> Loading config...
              </div>
            </div>

            <div class="rounded-3 border border-outline-gray-2 bg-surface-base p-5 shadow-sm">
              <div class="flex items-center justify-between mb-2">
                <h3 class="text-sm font-semibold text-ink-gray-9">Business Dictionary (Custom Instructions)</h3>
                <span class="rounded-full bg-surface-gray-2 border border-outline-gray-2 px-2 py-0.5 text-[10px] font-bold text-ink-gray-6">Session Scoped</span>
              </div>
              <p class="text-xs text-ink-gray-5 mb-4">Define terms like "Margin" or "Active User" so the AI generates the correct SQL logic.</p>
              
              <div class="space-y-4">
                <form @submit.prevent="addInstruction" class="flex items-end gap-3 rounded-3 bg-surface-gray-1 p-3 border border-outline-gray-2">
                  <div class="flex-1">
                    <label class="block text-[10px] font-bold uppercase tracking-wider text-ink-gray-5 mb-1">Term</label>
                    <input type="text" v-model="newInst.term" placeholder="e.g. Churn Rate" class="input w-full bg-surface-base text-sm" required />
                  </div>
                  <div class="flex-[2]">
                    <label class="block text-[10px] font-bold uppercase tracking-wider text-ink-gray-5 mb-1">Definition (SQL logic)</label>
                    <input type="text" v-model="newInst.definition" placeholder="COUNT(id) WHERE status='cancelled' / COUNT(id)" class="input w-full bg-surface-base font-mono text-sm" required />
                  </div>
                  <button type="submit" class="btn btn-primary h-9"><Plus class="h-4 w-4" /></button>
                </form>

                <div v-if="instructions.length === 0" class="text-center py-4 text-xs text-ink-gray-5 italic">
                  No custom instructions defined yet.
                </div>
                <div v-else class="space-y-2 max-h-60 overflow-y-auto pr-1">
                  <div v-for="inst in instructions" :key="inst.term" class="flex items-start justify-between rounded-2 border border-outline-gray-2 bg-surface-base p-3 shadow-sm group">
                    <div>
                      <div class="text-sm font-semibold text-ink-gray-9">{{ inst.term }}</div>
                      <div class="mt-1 font-mono text-[11px] text-ink-gray-6 bg-surface-gray-1 px-1.5 py-0.5 rounded-1 inline-block">{{ inst.definition }}</div>
                    </div>
                    <button type="button" @click="delInstruction(inst.term)" class="rounded text-ink-gray-4 hover:text-ink-red transition-colors p-1 opacity-0 group-hover:opacity-100" title="Remove">
                      <Trash2 class="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- Storage & Sweep Tab -->
          <section v-if="activeTab === 'storage'" class="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
            <div>
              <h2 class="text-lg font-semibold tracking-tight text-ink-gray-9">Storage & Ops (Admin)</h2>
              <p class="text-sm text-ink-gray-5">View server footprint and manage garbage collection.</p>
            </div>
            
            <div class="rounded-3 border border-outline-gray-2 bg-surface-base p-5 shadow-sm space-y-5">
              <div class="flex items-center justify-between border-b border-outline-gray-1 pb-4">
                <h3 class="text-sm font-semibold text-ink-gray-9">Server Metrics</h3>
                <button @click="loadStorage" class="text-[11px] flex items-center gap-1 text-primary hover:underline">
                  <RotateCcw class="h-3 w-3" /> Refresh
                </button>
              </div>
              
              <div v-if="storageData" class="grid grid-cols-2 sm:grid-cols-3 gap-4">
                <div class="rounded-2 bg-surface-gray-1 p-3 border border-outline-gray-2">
                  <span class="text-[10px] uppercase font-bold text-ink-gray-5 block mb-1">Live Sessions</span>
                  <span class="text-lg font-semibold text-ink-gray-9">{{ storageData.live_sessions }}</span>
                </div>
                <div class="rounded-2 bg-surface-gray-1 p-3 border border-outline-gray-2">
                  <span class="text-[10px] uppercase font-bold text-ink-gray-5 block mb-1">Uploads Footprint</span>
                  <span class="text-lg font-semibold text-ink-gray-9">{{ formatBytes(storageData.uploads_bytes) }}</span>
                </div>
                <div class="rounded-2 bg-surface-gray-1 p-3 border border-outline-gray-2">
                  <span class="text-[10px] uppercase font-bold text-ink-gray-5 block mb-1">DuckDB Size</span>
                  <span class="text-lg font-semibold text-ink-gray-9">{{ formatBytes(storageData.db_bytes) }}</span>
                </div>
                <div class="rounded-2 bg-surface-gray-1 p-3 border border-outline-gray-2">
                  <span class="text-[10px] uppercase font-bold text-ink-gray-5 block mb-1">DuckDB Tables</span>
                  <span class="text-lg font-semibold text-ink-gray-9">{{ storageData.table_count }}</span>
                </div>
                <div class="rounded-2 bg-surface-gray-1 p-3 border border-outline-gray-2">
                  <span class="text-[10px] uppercase font-bold text-ink-gray-5 block mb-1">Orphan Dirs</span>
                  <span class="text-lg font-semibold text-ink-gray-9" :class="storageData.orphan_dirs > 0 ? 'text-amber-600' : ''">{{ storageData.orphan_dirs }}</span>
                </div>
                <div class="rounded-2 bg-surface-gray-1 p-3 border border-outline-gray-2">
                  <span class="text-[10px] uppercase font-bold text-ink-gray-5 block mb-1">Disk Free</span>
                  <span class="text-lg font-semibold text-ink-gray-9">{{ formatBytes(storageData.disk_free) }}</span>
                </div>
              </div>
              <div v-else class="text-xs text-ink-gray-5 flex items-center gap-2">
                <Loader2 class="h-3 w-3 animate-spin" /> Loading metrics...
              </div>
            </div>

            <div class="rounded-3 border border-outline-gray-2 bg-surface-base p-5 shadow-sm">
              <div class="flex items-center justify-between mb-4">
                <h3 class="text-sm font-semibold text-ink-gray-9">Garbage Collection</h3>
                <span class="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-800">Operational</span>
              </div>
              <p class="text-xs text-ink-gray-5 mb-4 max-w-xl">
                The Engine automatically reclaims disk space from expired sessions every 30 minutes. You can force an immediate manual sweep to instantly wipe unowned tables and free up resources.
              </p>
              <button type="button" @click="runSweep" :disabled="isSweeping" class="flex items-center gap-2 rounded-2 bg-surface-gray-1 border border-outline-gray-2 px-4 py-2 text-xs font-bold text-ink-gray-7 hover:bg-surface-base hover:text-ink-gray-9 shadow-sm transition-colors disabled:opacity-50">
                <Trash2 v-if="!isSweeping" class="h-3.5 w-3.5" />
                <Loader2 v-else class="h-3.5 w-3.5 animate-spin" />
                {{ isSweeping ? 'Sweeping...' : 'Run Manual Sweep' }}
              </button>
            </div>
          </section>

          <!-- Shortcuts Tab -->
          <section v-if="activeTab === 'shortcuts'" class="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
            <div>
              <h2 class="text-lg font-semibold tracking-tight text-ink-gray-9">Keyboard Shortcuts</h2>
              <p class="text-sm text-ink-gray-5">Global keybindings to speed up your workflow.</p>
            </div>
            
            <div class="rounded-3 border border-outline-gray-2 bg-surface-base overflow-hidden shadow-sm">
              <table class="w-full text-left text-sm text-ink-gray-6">
                <thead class="bg-surface-gray-1 text-[11px] uppercase tracking-wider text-ink-gray-5 border-b border-outline-gray-2">
                  <tr>
                    <th class="px-4 py-3 font-semibold">Action</th>
                    <th class="px-4 py-3 font-semibold text-right">Shortcut</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-outline-gray-1">
                  <tr>
                    <td class="px-4 py-3">Open Command Palette</td>
                    <td class="px-4 py-3 text-right"><kbd class="rounded-2 border border-outline-gray-2 bg-surface-gray-1 px-1.5 py-0.5 text-xs font-semibold text-ink-gray-7 shadow-sm">⌘ K</kbd></td>
                  </tr>
                  <tr>
                    <td class="px-4 py-3">Undo last transform</td>
                    <td class="px-4 py-3 text-right"><kbd class="rounded-2 border border-outline-gray-2 bg-surface-gray-1 px-1.5 py-0.5 text-xs font-semibold text-ink-gray-7 shadow-sm">⌘ Z</kbd></td>
                  </tr>
                  <tr>
                    <td class="px-4 py-3">Redo transform</td>
                    <td class="px-4 py-3 text-right"><kbd class="rounded-2 border border-outline-gray-2 bg-surface-gray-1 px-1.5 py-0.5 text-xs font-semibold text-ink-gray-7 shadow-sm">⇧ ⌘ Z</kbd></td>
                  </tr>
                  <tr>
                    <td class="px-4 py-3">Toggle shortcuts cheatsheet</td>
                    <td class="px-4 py-3 text-right"><kbd class="rounded-2 border border-outline-gray-2 bg-surface-gray-1 px-1.5 py-0.5 text-xs font-semibold text-ink-gray-7 shadow-sm">?</kbd></td>
                  </tr>
                  <tr>
                    <td class="px-4 py-3">Close modals / dropdowns</td>
                    <td class="px-4 py-3 text-right"><kbd class="rounded-2 border border-outline-gray-2 bg-surface-gray-1 px-1.5 py-0.5 text-xs font-semibold text-ink-gray-7 shadow-sm">Esc</kbd></td>
                  </tr>
                  <tr>
                    <td class="px-4 py-3">Confirm inline edits / Generate SQL</td>
                    <td class="px-4 py-3 text-right"><kbd class="rounded-2 border border-outline-gray-2 bg-surface-gray-1 px-1.5 py-0.5 text-xs font-semibold text-ink-gray-7 shadow-sm">Enter</kbd></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

        </div>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Monitor, UserCircle, HardDrive, Trash2, Loader2, Sparkles, Keyboard, Plus, RotateCcw } from '@lucide/vue'
import { useAuth } from '../composables/useAuth'
import { useToasts } from '../composables/useToast'
import { useSession } from '../composables/useSession'
import { runAdminSweep, fetchAdminStorage, fetchAiConfig, changePassword, fetchInstructions, addInstruction as apiAddInstruction, deleteInstruction as apiDeleteInstruction } from '../services/api'
import { dashboardSettings, formatNumber, resolvedColor } from '../composables/useDashboardSettings'
import { CHART_PALETTES, normalizeHex } from '../utils/chartPalette'
import type { CustomInstruction } from '../types'

const { user, logout } = useAuth()
const { pushToast } = useToasts()
const { sessionUuid } = useSession()

const activeTab = ref('appearance')

const tabs = [
  { id: 'appearance', label: 'Appearance', icon: Monitor },
  { id: 'account', label: 'Account', icon: UserCircle },
  { id: 'ai', label: 'AI & Intelligence', icon: Sparkles },
  { id: 'storage', label: 'Storage (Admin)', icon: HardDrive },
  { id: 'shortcuts', label: 'Shortcuts', icon: Keyboard },
]

// --- Appearance ---
const currentTheme = ref(localStorage.getItem('spencer.theme') || 'light')
function setTheme(t: string) {
  currentTheme.value = t
  localStorage.setItem('spencer.theme', t)
  if (t === 'dark') {
    document.documentElement.setAttribute('data-theme', 'dark')
  } else {
    document.documentElement.removeAttribute('data-theme')
  }
  window.dispatchEvent(new Event('theme-changed'))
}

const palettes = CHART_PALETTES
const swatch = computed(() => resolvedColor(dashboardSettings.accent))
const hexText = computed({
  get: () => (dashboardSettings.accent ? dashboardSettings.accent : ''),
  set: (v: string) => {
    const norm = normalizeHex(v)
    dashboardSettings.accent = norm || '#000000'
  },
})

// --- Account ---
const passwords = ref({ current: '', new: '', confirm: '' })
const isChangingPassword = ref(false)
async function runChangePassword() {
  if (passwords.value.new !== passwords.value.confirm) {
    pushToast('New passwords do not match', 'error')
    return
  }
  if (passwords.value.new.length < 8) {
    pushToast('Password must be at least 8 characters', 'error')
    return
  }
  isChangingPassword.value = true
  try {
    await changePassword({ current_password: passwords.value.current, new_password: passwords.value.new })
    pushToast('Password updated successfully', 'success')
    passwords.value = { current: '', new: '', confirm: '' }
  } catch (e: any) {
    pushToast(e.response?.data?.detail || 'Failed to change password', 'error')
  } finally {
    isChangingPassword.value = false
  }
}

// --- AI & Intelligence ---
const aiConfig = ref<any>(null)
const instructions = ref<CustomInstruction[]>([])
const newInst = ref({ term: '', definition: '' })

async function loadAiTab() {
  try {
    try { aiConfig.value = await fetchAiConfig() } catch(e) { aiConfig.value = { provider: 'Unavailable (Requires Admin)', model: 'N/A', reasoning_effort: '' } }
    if (sessionUuid.value) {
      instructions.value = await fetchInstructions(sessionUuid.value)
    }
  } catch (e) {
    console.error("Failed to load AI config", e)
  }
}
async function addInstruction() {
  if (!sessionUuid.value) return
  try {
    await apiAddInstruction(sessionUuid.value, newInst.value)
    instructions.value = await fetchInstructions(sessionUuid.value)
    newInst.value = { term: '', definition: '' }
    pushToast('Instruction added', 'success')
  } catch (e: any) {
    pushToast(e.response?.data?.detail || 'Failed to add instruction', 'error')
  }
}
async function delInstruction(term: string) {
  if (!sessionUuid.value) return
  try {
    await apiDeleteInstruction(sessionUuid.value, term)
    instructions.value = await fetchInstructions(sessionUuid.value)
  } catch (e: any) {
    pushToast(e.response?.data?.detail || 'Failed to delete instruction', 'error')
  }
}

// --- Storage & Admin ---
const storageData = ref<any>(null)
const isSweeping = ref(false)

async function loadStorage() {
  try {
    try { storageData.value = await fetchAdminStorage() } catch(e) { }
  } catch (e) {
    console.error("Failed to load storage", e)
  }
}

async function runSweep() {
  isSweeping.value = true
  try {
    const data = await runAdminSweep()
    pushToast(`Sweep complete. Cleared ${data.sessions_reaped || 0} dead sessions.`, 'success')
    await loadStorage()
  } catch (e: any) {
    pushToast(e.response?.data?.detail || 'Failed to run sweep', 'error')
  } finally {
    isSweeping.value = false
  }
}

function formatBytes(bytes: number, decimals = 2) {
  if (!+bytes) return '0 Bytes'
  const k = 1024
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`
}

onMounted(() => {
  loadAiTab()
  loadStorage()
})
</script>
