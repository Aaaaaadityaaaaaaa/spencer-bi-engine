// Categorical chart palette (Phase 5 / TASK-011).
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
  'oklch(0.587 0.174 252.167)', // blue    -- matches --primary-6
  'oklch(0.600 0.130 156.000)', // green
  'oklch(0.680 0.140 64.000)',  // amber
  'oklch(0.600 0.190 27.000)',  // red
  'oklch(0.580 0.170 300.000)', // violet
  'oklch(0.620 0.110 195.000)', // teal
  'oklch(0.620 0.180 340.000)', // magenta
  'oklch(0.670 0.150 130.000)', // lime
]

/** The brand accent, for single-series bar/line charts. */
export const CHART_PRIMARY = CHART_PALETTE[0]

/** Cycle the palette so any number of categories gets a colour. */
export function paletteColor(index: number): string {
  return CHART_PALETTE[index % CHART_PALETTE.length]
}

// TASK-036 (Power BI Canvas, part 4): per-tile CARD BACKGROUND tints. Light, low-chroma
// fills (paired 1:1 with the CHART_PALETTE hues) so on-card ink stays readable; `null` ⇒
// the default surface. Handed straight to CSS `background-color` (which parses oklch),
// exactly as the series palette is handed to ECharts.
export const CHART_BG_PALETTE: readonly string[] = [
  'oklch(0.968 0.017 252.167)', // blue tint
  'oklch(0.972 0.015 156.000)', // green tint
  'oklch(0.975 0.020 84.000)',  // amber tint
  'oklch(0.968 0.020 27.000)',  // red tint
  'oklch(0.967 0.018 300.000)', // violet tint
  'oklch(0.972 0.014 195.000)', // teal tint
  'oklch(0.967 0.018 340.000)', // magenta tint
  'oklch(0.975 0.018 130.000)', // lime tint
]

/** Fallback swatch for a native <input type="color"> when the current colour is a preset
 *  (oklch) the picker can't display — a native colour input only renders #rrggbb, so an
 *  oklch value would silently reset it to #000000. Purely the picker's starting swatch;
 *  choosing a colour always emits a fresh hex. */
export const PICKER_FALLBACK = '#4f7cf7'

const HEX6 = /^#?([0-9a-fA-F]{6})$/

/** Normalise a user-typed hex ("4f7cf7", "#4F7CF7") to "#4f7cf7"; null if it is not 6-hex. */
export function normalizeHex(raw: string): string | null {
  const m = raw.trim().match(HEX6)
  return m ? `#${m[1].toLowerCase()}` : null
}

/** A colour a native <input type="color"> can display, or `fallback`. Only #rrggbb
 *  round-trips through that control; anything else (a preset oklch) yields the fallback. */
export function asHexInput(c: string | null | undefined, fallback = PICKER_FALLBACK): string {
  return typeof c === 'string' ? (normalizeHex(c) ?? fallback) : fallback
}

// Chart chrome, pulled from the same token values (canvas cannot read CSS variables).
export const CHART_INK = 'oklch(0.439 0 0)' // --ink-gray-6, axis labels
export const CHART_INK_FAINT = 'oklch(0.683 0 0)' // --ink-gray-4, split lines
export const CHART_SPLIT_LINE = 'oklch(0.946 0 0)' // --outline-gray-1
export const CHART_FONT =
  'Inter, ui-sans-serif, system-ui, sans-serif'
