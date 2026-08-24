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

// Chart chrome, pulled from the same token values (canvas cannot read CSS variables).
export const CHART_INK = 'oklch(0.439 0 0)' // --ink-gray-6, axis labels
export const CHART_INK_FAINT = 'oklch(0.683 0 0)' // --ink-gray-4, split lines
export const CHART_SPLIT_LINE = 'oklch(0.946 0 0)' // --outline-gray-1
export const CHART_FONT =
  'Inter, ui-sans-serif, system-ui, sans-serif'
