// Column classification for the Canvas dashboard (Phase 5 / TASK-011).
//
// The backend reports each column's RAW DuckDB type string (e.g. "BIGINT",
// "DECIMAL(10,2)", "TIMESTAMP WITH TIME ZONE"). The dashboard needs to know which
// columns are valid measures (numeric), which make good time axes (temporal), and
// which are groupable labels (everything else) -- so this is the one place that
// interprets those strings. Kept as a pure function with no Vue dependency so it is
// trivially testable and reusable.

import type { ColumnMeta } from '../types'

export type ColumnKind = 'numeric' | 'temporal' | 'categorical'

// DuckDB numeric aliases. DECIMAL/NUMERIC carry precision ("DECIMAL(10,2)") and are
// matched after the parenthesized part is stripped.
const NUMERIC = new Set([
  'BIGINT', 'INT8', 'LONG',
  'INTEGER', 'INT', 'INT4', 'SIGNED',
  'SMALLINT', 'INT2', 'SHORT',
  'TINYINT', 'INT1',
  'HUGEINT', 'UHUGEINT',
  'UBIGINT', 'UINTEGER', 'USMALLINT', 'UTINYINT',
  'DOUBLE', 'FLOAT8',
  'FLOAT', 'FLOAT4', 'REAL',
  'DECIMAL', 'NUMERIC',
])

// INTERVAL is deliberately NOT temporal: it is a duration, not a point in time, so
// ordering a series by it is meaningless. It falls through to categorical.
const TEMPORAL = new Set(['DATE', 'TIME', 'DATETIME'])

/** Map a raw DuckDB type string to the kind the dashboard cares about. */
export function columnKind(type: string): ColumnKind {
  // "DECIMAL(10,2)" -> "DECIMAL"; "TIMESTAMP WITH TIME ZONE" keeps its suffix.
  const base = type.toUpperCase().trim().replace(/\(.*$/, '').trim()
  if (NUMERIC.has(base)) return 'numeric'
  // Covers TIMESTAMP, TIMESTAMPTZ, TIMESTAMP_NS, TIMESTAMP WITH TIME ZONE, ...
  if (TEMPORAL.has(base) || base.startsWith('TIMESTAMP') || base.startsWith('TIME ')) {
    return 'temporal'
  }
  return 'categorical'
}

export function numericColumns(columns: ColumnMeta[]): ColumnMeta[] {
  return columns.filter((c) => columnKind(c.type) === 'numeric')
}

export function temporalColumns(columns: ColumnMeta[]): ColumnMeta[] {
  return columns.filter((c) => columnKind(c.type) === 'temporal')
}

export function categoricalColumns(columns: ColumnMeta[]): ColumnMeta[] {
  return columns.filter((c) => columnKind(c.type) === 'categorical')
}

/** Columns usable as a group-by dimension: labels first, then time axes. */
export function dimensionColumns(columns: ColumnMeta[]): ColumnMeta[] {
  // Allow ANY column to be a dimension (Power BI style)
  return columns
}

/** Look up a column's kind by name; unknown names read as categorical (safe default). */
export function kindOf(columns: ColumnMeta[], name: string | null): ColumnKind | null {
  if (!name) return null
  const col = columns.find((c) => c.name === name)
  return col ? columnKind(col.type) : null
}
