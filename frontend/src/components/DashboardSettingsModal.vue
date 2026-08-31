<script setup lang="ts">
// Power BI–style report-level settings window. Bound live to the global `dashboardSettings`
// reactive store, so every change applies instantly across the board and persists to
// localStorage. `apply-all` asks the Canvas to push the current accent + show-values onto
// every existing tile (overriding their local choices); `close` dismisses the window.
import { computed } from 'vue'
import { Settings2, X } from '@lucide/vue'
import {
  dashboardSettings,
  resetDashboardSettings,
  resolvedColor,
  formatNumber,
} from '../composables/useDashboardSettings'
import { normalizeHex } from '../utils/chartPalette'

const emit = defineEmits<{ (e: 'close'): void; (e: 'apply-all'): void }>()

// A <input type="color"> only renders #rrggbb; show the resolved colour (brand default when
// the global accent is unset) so the swatch is never blank.
const swatch = computed(() => resolvedColor(dashboardSettings.accent))
const hexText = computed({
  get: () => (dashboardSettings.accent ? dashboardSettings.accent : ''),
  set: (v: string) => {
    const norm = normalizeHex(v)
    dashboardSettings.accent = norm // null clears back to the brand default
  },
})

function clearAccent(): void {
  dashboardSettings.accent = null
}

const decimalOptions = [0, 1, 2, 3, 4]
</script>

<template>
  <div
    class="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4"
    @click.self="emit('close')"
  >
    <div
      class="js-export-exclude flex max-h-[85vh] w-full max-w-md flex-col overflow-hidden rounded-3 border border-outline-gray-2 bg-surface-base shadow-xl"
    >
      <!-- Header -->
      <div class="flex items-center justify-between border-b border-outline-gray-2 px-4 py-3">
        <div class="flex items-center gap-2">
          <Settings2 class="h-4 w-4 text-primary" />
          <h2 class="text-sm font-semibold text-ink-gray-9">Dashboard settings</h2>
        </div>
        <button
          type="button"
          class="rounded-2 p-1 text-ink-gray-6 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-9"
          title="Close"
          @click="emit('close')"
        >
          <X class="h-4 w-4" />
        </button>
      </div>

      <!-- Body -->
      <div class="flex-1 space-y-5 overflow-y-auto px-4 py-4">
        <!-- Number format -->
        <section>
          <h3 class="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-gray-5">
            Number format
          </h3>
          <div class="space-y-3">
            <div class="flex items-center justify-between gap-3">
              <label class="text-xs text-ink-gray-7">Decimal places</label>
              <select
                v-model.number="dashboardSettings.decimalPlaces"
                class="rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-1 text-xs text-ink-gray-8"
              >
                <option v-for="d in decimalOptions" :key="d" :value="d">{{ d }}</option>
              </select>
            </div>
            <label class="flex items-center justify-between gap-3">
              <span class="text-xs text-ink-gray-7">Thousands separator</span>
              <input
                type="checkbox"
                v-model="dashboardSettings.thousands"
                class="h-4 w-4 accent-primary"
              />
            </label>
            <label class="flex items-center justify-between gap-3">
              <span class="text-xs text-ink-gray-7">Compact (K / M / B)</span>
              <input
                type="checkbox"
                v-model="dashboardSettings.compact"
                class="h-4 w-4 accent-primary"
              />
            </label>
            <p class="text-[11px] text-ink-gray-5">
              Example:
              <span class="font-medium text-ink-gray-7">
                {{ formatNumber(1234567.891) }}
              </span>
            </p>
          </div>
        </section>

        <!-- Theme -->
        <section>
          <h3 class="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-gray-5">Theme</h3>
          <div class="space-y-3">
            <div class="flex items-center justify-between gap-3">
              <label class="text-xs text-ink-gray-7">Accent colour</label>
              <div class="flex items-center gap-2">
                <input
                  type="color"
                  :value="swatch"
                  class="h-7 w-9 cursor-pointer rounded-2 border border-outline-gray-2 bg-transparent"
                  @input="dashboardSettings.accent = ($event.target as HTMLInputElement).value"
                />
                <input
                  type="text"
                  v-model="hexText"
                  :placeholder="'#hex / blank = brand'"
                  class="w-32 rounded-2 border border-outline-gray-2 bg-surface-base px-2 py-1 text-xs text-ink-gray-8"
                />
              </div>
            </div>
            <button
              type="button"
              class="text-[11px] text-ink-gray-5 underline-offset-2 hover:text-primary hover:underline"
              @click="clearAccent"
            >
              Reset to brand default
            </button>
          </div>
        </section>

        <!-- Charts -->
        <section>
          <h3 class="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-gray-5">Charts</h3>
          <label class="flex items-center justify-between gap-3">
            <span class="text-xs text-ink-gray-7">Show values on charts by default</span>
            <input
              type="checkbox"
              v-model="dashboardSettings.showValues"
              class="h-4 w-4 accent-primary"
            />
          </label>
        </section>
      </div>

      <!-- Footer -->
      <div class="flex items-center justify-between gap-2 border-t border-outline-gray-2 px-4 py-3">
        <button
          type="button"
          class="text-[11px] text-ink-gray-5 underline-offset-2 hover:text-ink-red hover:underline"
          @click="resetDashboardSettings()"
        >
          Reset all
        </button>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="rounded-3 border border-outline-gray-2 bg-surface-base px-3 py-1.5 text-xs text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
            @click="emit('close')"
          >
            Close
          </button>
          <button
            type="button"
            class="rounded-3 bg-primary px-3 py-1.5 text-xs font-medium text-ink-white shadow-sm transition-colors hover:bg-primary-7"
            title="Push the current accent + show-values onto every tile"
            @click="emit('apply-all')"
          >
            Apply to all tiles
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
