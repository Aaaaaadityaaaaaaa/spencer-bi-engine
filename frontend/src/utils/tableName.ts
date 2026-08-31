// Wave 5 alias display: the real DuckDB table is namespaced `t_<session_uuid>_<original>`
// for uniqueness + tenant isolation (see backend/services/alias_service.py). The user-facing
// name is the original upload name; strip the `t_<uuid>_` prefix for display so the UI shows
// `messy_sales_dataset_100k` instead of the long physical name. The backend still resolves
// the original name back to the physical name at query time, so this is display-only.

// Strip a leading `t_<session_uuid>_` namespace. Works with or without the session uuid:
// when it's known we match the exact prefix; otherwise we fall back to a generic
// `t_<hex-with-underscores>_` pattern so the original name still shows.
export function displayTableName(physical: string | null | undefined, sessionUuid: string | null | undefined): string {
  if (!physical) return ''
  if (sessionUuid) {
    const prefix = `t_${sessionUuid.replace(/-/g, '_')}_`
    if (physical.startsWith(prefix)) return physical.slice(prefix.length)
  }
  return stripNamespace(physical)
}

// Backwards-compatible helper used by the Query Console header: takes only the physical name.
export function friendlyTableName(physical: string | null | undefined): string {
  return stripNamespace(physical ?? '')
}

// Display-only: rewrite the long `t_<uuid>_<original>` physical identifiers in a SQL string
// back to their short original names. The backend still resolves the original name on run
// (alias_service.resolve_aliases), so this is purely cosmetic and never changes what executes.
export function displaySql(sql: string | null | undefined, sessionUuid: string | null | undefined): string {
  if (!sql || !sessionUuid) return sql ?? ''
  const prefix = `t_${sessionUuid.replace(/-/g, '_')}_`
  const escaped = prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  // Capture the table-name remainder (alphanumerics + underscore, so original names with
  // underscores survive intact) and drop just the leading namespace prefix.
  return sql.replace(new RegExp(`${escaped}([A-Za-z0-9_]+)`, 'g'), '$1')
}

function stripNamespace(physical: string): string {
  const m = physical.match(/^t_[0-9a-f]+(?:_[0-9a-f]+)*_(.*)$/i)
  return m ? m[1] : physical
}
