// Which aggregations are legal for a given measure, and how to label them.
// This mirrors the backend's validation in services/aggregate_service.py::_validate --
// the client narrows the pickers so a user cannot easily build a request the server
// will reject, but the SERVER remains the authority (a stale column list would still
// produce a friendly 400 rather than a wrong number).

import type { Aggregation, ColumnMeta } from '../types'
import { kindOf } from './columnKind'

export const AGG_LABEL: Record<Aggregation, string> = {
  sum: 'Sum',
  avg: 'Average',
  count: 'Count',
  count_distinct: 'Distinct count',
  min: 'Min',
  max: 'Max',
}

/**
 * Legal aggregations for `measure` (null measure => COUNT(*) only, matching the
 * backend rule that only plain `count` may omit a measure).
 */
export function allowedAggregations(columns: ColumnMeta[], measure: string | null): Aggregation[] {
  if (measure === null) return ['count']
  const kind = kindOf(columns, measure)
  if (kind === 'numeric') return ['sum', 'avg', 'min', 'max', 'count', 'count_distinct']
  if (kind === 'temporal') return ['min', 'max', 'count', 'count_distinct']
  // Categorical (or a column that has since been dropped): no arithmetic.
  return ['count', 'count_distinct']
}

/**
 * Coerce an aggregation to one that is legal for `measure`. Used when the user
 * switches measure and the previously-selected aggregation no longer applies
 * (e.g. Sum of revenue -> switch to a text column).
 */
export function coerceAggregation(
  columns: ColumnMeta[],
  measure: string | null,
  current: Aggregation,
): Aggregation {
  const allowed = allowedAggregations(columns, measure)
  if (allowed.includes(current)) return current
  return allowed[0] ?? 'count'
}
