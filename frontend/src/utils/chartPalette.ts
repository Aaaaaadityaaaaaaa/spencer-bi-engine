// Categorical chart palette
//
// The design tokens in style.css only carry four hues (blue / green / amber / red),
// which is not enough for a pie chart or a multi-category series. These eight hues
// extend that language rather than replacing it: the first entry IS --primary-6
// (Frappe blue) so a single-series bar/line chart matches the rest of the UI, and the
// remaining seven hold a similar lightness (~0.58-0.68) and chroma so no one slice
// screams louder than its neighbours.
//
// Values are oklch strings, consistent with every other colour in the app. ECharts
// renders to <canvas>, and Canvas2D resolves any CSS colour the browser can parse
// (oklch: Chrome 111+), so these are handed to ECharts verbatim.

export const CHART_PALETTE: readonly string[] = [
  '#83bfc8', // primary cyan/teal (requested by user)
  '#f97316', // orange
  '#8b5cf6', // violet
  '#10b981', // emerald
  '#ef4444', // red
  '#3b82f6', // blue
  '#f59e0b', // amber
  '#ec4899', // pink
]

/** The brand accent, for single-series bar/line charts. */
export const CHART_PRIMARY = CHART_PALETTE[0]

/** Cycle the palette so any number of categories gets a colour. */
export function paletteColor(index: number): string {
  return CHART_PALETTE[index % CHART_PALETTE.length]
}

export interface NamedPalette {
  id: string
  label: string
  colors: string[]
}
export const CHART_PALETTES: NamedPalette[] = [
  { id: 'default', label: 'Spencer (Default)', colors: [...CHART_PALETTE] },
  {
    id: 'category10',
    label: 'Category 10',
    colors: [
      '#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f',
      '#edc948', '#b07aa1', '#ff9da7', '#9c755f', '#bab0ac',
    ],
  },
  {
    id: 'vivid',
    label: 'Vivid',
    colors: [
      '#ef4444', '#f97316', '#eab308', '#22c55e', '#06b6d4',
      '#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6', '#f43f5e',
    ],
  },
  {
    id: 'pastel',
    label: 'Pastel',
    colors: [
      '#a3c4f3', '#ffcfd2', '#b9fbc0', '#fff1a8', '#c8b6ff',
      '#ffd6a5', '#bde0fe', '#cdb4db', '#ffc8dd', '#a0c4ff',
    ],
  },
  {
    id: 'earth',
    label: 'Earth',
    colors: [
      '#7f5539', '#9c6644', '#b08968', '#ddb892', '#a3b18a',
      '#588157', '#3a5a40', '#344e41', '#dad7cd', '#a98467',
    ],
  },
]
export function paletteById(id: string | null | undefined): string[] {
  if (!id) return [...CHART_PALETTE]
  return CHART_PALETTES.find((p) => p.id === id)?.colors ?? [...CHART_PALETTE]
}
/** Colour for category `index` using the tile's chosen palette (defaults to the brand set). */
export function paletteColorFor(paletteId: string | null | undefined, index: number): string {
  const p = paletteById(paletteId)
  return p[index % p.length]
}

export const CHART_BG_PALETTE: readonly string[] = [
  '#e0f2f5', // cyan/teal tint
  '#fff7ed', // orange tint
  '#f5f3ff', // violet tint
  '#ecfdf5', // emerald tint
  '#fef2f2', // red tint
  '#eff6ff', // blue tint
  '#fffbeb', // amber tint
  '#fdf2f8', // pink tint
]

export const PICKER_FALLBACK = '#83bfc8'

const HEX6 = /^#?([0-9a-fA-F]{6})$/

export function normalizeHex(raw: string): string | null {
  const m = raw.trim().match(HEX6)
  return m ? `#${m[1].toLowerCase()}` : null
}

export function asHexInput(c: string | null | undefined, fallback = PICKER_FALLBACK): string {
  return typeof c === 'string' ? (normalizeHex(c) ?? fallback) : fallback
}

export const CHART_INK = '#3f3f46' // --ink-gray-6
export const CHART_INK_FAINT = '#a1a1aa' // --ink-gray-4
export const CHART_SPLIT_LINE = '#e4e4e7' // --outline-gray-1
export const CHART_WHITE = '#ffffff'
export const CHART_FONT = '"Geist", ui-sans-serif, system-ui, sans-serif'
