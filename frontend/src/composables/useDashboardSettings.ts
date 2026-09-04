// Global, report-level dashboard settings (Power BI–style). These are the defaults that
// apply across EVERY tile on the board; each tile can still override them locally (a tile's
// own colour picker, its own show-values toggle). The settings live in one place so the user
// doesn't have to repeat the same choice on every chart/card.
//
// Persisted to localStorage (per browser) so a reload restores the chosen formatting. This is
// pure presentation state -- it never touches the query/aggregation layer or the schema.
import { reactive, watch } from 'vue'
import { CHART_PRIMARY } from '../utils/chartPalette'

export interface DashboardSettings {
  /** Fractional digits shown on every numeric value (0-4). */
  decimalPlaces: number
  /** Use thousands separators (1,234 vs 1234). */
  thousands: boolean
  /** Abbreviate large numbers (1.2K / 3.4M / 5.6B). Keeps axis labels and KPI
   *  values from overflowing once a dataset reaches six or seven figures. */
  compact: boolean
  /** Single-series / card accent applied to all visuals that have no explicit colour. null = brand default. */
  accent: string | null
  /** The default categorical palette for charts. */
  paletteId: string | null
  /** Default "show values on chart" for new charts (and what "Apply to all" pushes). */
  showValues: boolean
}

const STORAGE_KEY = 'spencer.dashboardSettings'

function clampInt(n: unknown, lo: number, hi: number, fallback: number): number {
  const v = typeof n === 'number' ? Math.round(n) : fallback
  return Math.max(lo, Math.min(hi, Number.isFinite(v) ? v : fallback))
}

function load(): DashboardSettings {
  const fallback: DashboardSettings = { decimalPlaces: 0, thousands: true, compact: false, accent: '#000000', showValues: false, paletteId: 'monochrome' }
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return fallback
    const p = JSON.parse(raw)
    return {
      decimalPlaces: clampInt(p.decimalPlaces, 0, 4, fallback.decimalPlaces),
      thousands: typeof p.thousands === 'boolean' ? p.thousands : fallback.thousands,
      compact: typeof p.compact === 'boolean' ? p.compact : fallback.compact,
      accent: typeof p.accent === 'string' && p.accent ? p.accent : null,
      showValues: typeof p.showValues === 'boolean' ? p.showValues : fallback.showValues,
      paletteId: typeof p.paletteId === 'string' && p.paletteId ? p.paletteId : null,
    }
  } catch {
    return fallback
  }
}

export const dashboardSettings = reactive<DashboardSettings>(load())

watch(
  dashboardSettings,
  () => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...dashboardSettings }))
    } catch {
      /* private mode / quota -- ignore, settings still live for the session */
    }
  },
  { deep: true },
)

const fmtCache = new Map<string, Intl.NumberFormat>()

/** Per-tile number overrides (TASK-044) — null/undefined ⇒ fall back to the global setting. */
export interface NumberOverrides {
  decimals?: number | null
  thousands?: boolean | null
  currency?: boolean | null
  /** Abbreviate (1.2K / 3.4M). null ⇒ use the report-level setting. */
  compact?: boolean | null
}
function numberFormatter(overrides?: NumberOverrides): Intl.NumberFormat {
  const decimals = overrides?.decimals ?? dashboardSettings.decimalPlaces
  const thousands = overrides?.thousands ?? dashboardSettings.thousands
  const currency = overrides?.currency ?? false
  const compact = overrides?.compact ?? dashboardSettings.compact
  const key = `${decimals}|${thousands ? 1 : 0}|${currency ? 1 : 0}|${compact ? 1 : 0}`
  let f = fmtCache.get(key)
  if (!f) {
    f = new Intl.NumberFormat(undefined, {
      style: currency ? 'currency' : 'decimal',
      currency: 'USD',
      minimumFractionDigits: decimals,
      // Compact needs at least ONE decimal to stay useful: at 0 the formatter
      // rounds 1,234,567 down to "1M" — accurate but useless. One decimal gives
      // "1.2M" / "45.7K" while a round 1,000 still prints "1K" (min stays 0).
      maximumFractionDigits: compact ? Math.max(decimals, 1) : decimals,
      // `useGrouping: 'auto'` is required with compact notation in some engines;
      // a plain boolean there is ignored and grouping silently disappears.
      useGrouping: (thousands ? 'auto' : false) as any,
      notation: compact ? 'compact' : 'standard',
      compactDisplay: 'short',
    })
    fmtCache.set(key, f)
  }
  return f
}

/** Format any value with the global number rules (or per-tile overrides); non-numbers pass
 *  through (null -> em dash handled by callers). */
export function formatNumber(v: unknown, overrides?: NumberOverrides): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return v == null ? '—' : String(v)
  return numberFormatter(overrides).format(v)
}

/** Resolve a tile's effective colour: explicit override first, else the global accent, else the brand default. */
export function effectiveColor(color?: string | null): string | null {
  if (color && color.trim()) return color
  return dashboardSettings.accent || null
}

/** The concrete colour to draw with (never null) -- brand default when nothing else applies. */
export function resolvedColor(color?: string | null): string {
  return effectiveColor(color) || CHART_PRIMARY
}

export function resetDashboardSettings(): void {
  dashboardSettings.decimalPlaces = 0
  dashboardSettings.thousands = true
  dashboardSettings.compact = false
  dashboardSettings.accent = '#000000'
  dashboardSettings.showValues = false
  dashboardSettings.paletteId = 'monochrome'
}

export function useDashboardSettings() {
  return { settings: dashboardSettings, formatNumber, effectiveColor, resolvedColor, resetDashboardSettings }
}
