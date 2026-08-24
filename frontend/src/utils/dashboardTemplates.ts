// Dashboard templates (TASK-026 / Wave 6, feature #16).
//
// A template is a pure function from the current schema (ColumnMeta[]) to a set of tile
// CONFIGS -- the same {kpis, charts} snapshot shape a saved dashboard restores. It is a
// one-click "build me a sensible starting dashboard for THIS data" that goes beyond the
// single auto-seeded chart: a few KPIs plus two or three coordinated charts, chosen from
// the column kinds actually present.
//
// Ids are deliberately absent here: ChartCanvas owns the id counters and assigns them
// when it installs a snapshot (exactly as it does for auto-seed and Add-tile), so a
// template can never mint an id that collides with a live tile.
//
// Each template declares `applicable(columns)` so the picker only ever offers one that
// the schema can satisfy -- a "Category breakdown" is hidden when there are no
// categorical columns, rather than building an empty dashboard.
import type { ChartConfig, ColumnMeta, KpiConfig } from '../types'
import { categoricalColumns, numericColumns, temporalColumns } from './columnKind'

/** A KPI config before ChartCanvas assigns its runtime id. */
export type KpiSeed = Omit<KpiConfig, 'id'>

export interface TemplateSnapshot {
  kpis: KpiSeed[]
  charts: ChartConfig[]
}

export interface DashboardTemplate {
  id: string
  label: string
  description: string
  /** True when the current schema has the column kinds this template needs. */
  applicable: (columns: ColumnMeta[]) => boolean
  build: (columns: ColumnMeta[]) => TemplateSnapshot
}

// The most readable group-by dimension, mirroring ChartCanvas.seed(): a categorical
// column that actually groups (cardinality > 1) and stays legible (<= 50 distinct),
// else the first grouping categorical, else the first temporal, else null.
function bestDimension(cols: ColumnMeta[]): ColumnMeta | null {
  const cats = categoricalColumns(cols)
  const temps = temporalColumns(cols)
  const grouping = cats.filter((c) => c.cardinality === undefined || c.cardinality > 1)
  const readable = grouping.find((c) => c.cardinality !== undefined && c.cardinality <= 50)
  return readable ?? grouping[0] ?? temps[0] ?? null
}

// Cap KPI seeds at the Canvas limit (MAX_KPIS = 6) so a wide table can't overflow the row.
function capKpis(seeds: KpiSeed[]): KpiSeed[] {
  return seeds.slice(0, 6)
}

// ---------------------------------------------------------------------------------
// 1. Overview -- always applicable. A row count, the headline numeric summarised two
//    ways, and one chart over the best dimension. This is the auto-seed, promoted to a
//    named, re-appliable template.
const overview: DashboardTemplate = {
  id: 'overview',
  label: 'Overview',
  description: 'Row count, a headline metric, and one chart over the best dimension.',
  applicable: () => true,
  build(cols) {
    const nums = numericColumns(cols)
    const cats = categoricalColumns(cols)
    const temps = temporalColumns(cols)

    const kpis: KpiSeed[] = [{ measure: null, aggregation: 'count' }]
    if (nums.length > 0) {
      kpis.push({ measure: nums[0].name, aggregation: 'sum' })
      kpis.push({ measure: nums[0].name, aggregation: 'avg' })
    } else if (cats.length > 0) {
      kpis.push({ measure: cats[0].name, aggregation: 'count_distinct' })
    }

    const dim = bestDimension(cols)
    const isTemporal = dim !== null && temps.some((t) => t.name === dim.name)
    const charts: ChartConfig[] = [
      {
        dimension: dim?.name ?? null,
        series: null,
        measure: nums[0]?.name ?? null,
        aggregation: nums.length > 0 ? 'sum' : 'count',
        chartType: isTemporal ? 'line' : 'bar',
      },
    ]
    return { kpis: capKpis(kpis), charts }
  },
}

// ---------------------------------------------------------------------------------
// 2. Numbers focus -- for numeric-heavy data. The first metric summarised four ways
//    (sum / avg / min / max), plus the second metric's sum; a ranked bar and a
//    composition pie of the headline metric by the best dimension.
const numbersFocus: DashboardTemplate = {
  id: 'numbers',
  label: 'Numbers focus',
  description: 'A metric summarised sum / avg / min / max, with ranked and composition charts.',
  applicable: (cols) => numericColumns(cols).length > 0,
  build(cols) {
    const nums = numericColumns(cols)
    const temps = temporalColumns(cols)
    const m0 = nums[0].name

    const kpis: KpiSeed[] = [
      { measure: m0, aggregation: 'sum' },
      { measure: m0, aggregation: 'avg' },
      { measure: m0, aggregation: 'min' },
      { measure: m0, aggregation: 'max' },
    ]
    if (nums.length > 1) kpis.push({ measure: nums[1].name, aggregation: 'sum' })

    const dim = bestDimension(cols)
    const isTemporal = dim !== null && temps.some((t) => t.name === dim.name)
    const charts: ChartConfig[] = [
      {
        dimension: dim?.name ?? null,
        series: null,
        measure: m0,
        aggregation: 'sum',
        chartType: isTemporal ? 'line' : 'bar',
      },
    ]
    // A composition view only reads well over a categorical dimension, not a date axis.
    if (dim && !isTemporal) {
      charts.push({ dimension: dim.name, series: null, measure: m0, aggregation: 'sum', chartType: 'pie' })
    }
    return { kpis: capKpis(kpis), charts }
  },
}

// ---------------------------------------------------------------------------------
// 3. Category breakdown -- for categorical data. Counts and distinct-counts as KPIs, a
//    ranked bar, and (when a second categorical + a numeric both exist) a STACKED bar
//    using the Wave-5 2-D breakdown, so the template showcases dimension x series.
const categoryBreakdown: DashboardTemplate = {
  id: 'category',
  label: 'Category breakdown',
  description: 'Distinct-value counts and a ranked bar; a stacked breakdown when the data allows.',
  applicable: (cols) => categoricalColumns(cols).length > 0,
  build(cols) {
    const cats = categoricalColumns(cols)
    const nums = numericColumns(cols)
    const c0 = cats[0].name
    const measure = nums[0]?.name ?? null
    const agg = nums.length > 0 ? 'sum' : 'count'

    const kpis: KpiSeed[] = [
      { measure: null, aggregation: 'count' },
      { measure: c0, aggregation: 'count_distinct' },
    ]
    if (cats.length > 1) kpis.push({ measure: cats[1].name, aggregation: 'count_distinct' })
    if (measure) kpis.push({ measure, aggregation: 'sum' })

    const charts: ChartConfig[] = [
      { dimension: c0, series: null, measure, aggregation: agg, chartType: 'bar' },
      { dimension: c0, series: null, measure, aggregation: agg, chartType: 'pie' },
    ]
    // A second categorical + a real measure => a genuine 2-D stacked bar (c0 x c1).
    if (cats.length > 1 && measure) {
      charts.push({
        dimension: c0,
        series: cats[1].name,
        measure,
        aggregation: 'sum',
        chartType: 'stacked',
      })
    }
    return { kpis: capKpis(kpis), charts }
  },
}

const ALL_TEMPLATES: DashboardTemplate[] = [overview, numbersFocus, categoryBreakdown]

/** The templates whose column-kind prerequisites the current schema satisfies. */
export function availableTemplates(columns: ColumnMeta[]): DashboardTemplate[] {
  return ALL_TEMPLATES.filter((t) => t.applicable(columns))
}

/** Build one template by id (null if unknown or not applicable to this schema). */
export function buildTemplate(id: string, columns: ColumnMeta[]): TemplateSnapshot | null {
  const t = ALL_TEMPLATES.find((x) => x.id === id)
  if (!t || !t.applicable(columns)) return null
  return t.build(columns)
}
