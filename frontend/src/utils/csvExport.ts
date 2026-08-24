// Dependency-free client-side export helpers: build CSV/JSON/TSV from rows the API
// already returned, copy to the clipboard, and trigger browser downloads (including
// server-encoded blobs like .xlsx/.parquet). Shared by the Query Engine result table
// and the Table grid's export menu. Frontend-only (camelCase); nothing built here is
// sent back to the server, so there's no SQL/injection surface (unlike transform paths).
import type { DataColumn } from '../types'

// RFC-4180 field escaping: wrap a field in double quotes when it contains a comma,
// a double quote, or a CR/LF, and double any embedded quotes. Everything else is
// emitted bare so plain values stay human-readable.
function escapeField(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return '"' + value.replace(/"/g, '""') + '"'
  }
  return value
}

// Match the grid's on-screen coercion so the file mirrors exactly what the user sees:
// NULL/undefined -> empty cell; objects/arrays -> compact JSON; everything else -> String.
function cellToString(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** Build an RFC-4180 CSV string: a header row of column names + one row per record. */
export function toCsv(columns: DataColumn[], rows: Record<string, unknown>[]): string {
  const names = columns.map((c) => c.name)
  const header = names.map(escapeField).join(',')
  const body = rows.map((row) => names.map((n) => escapeField(cellToString(row[n]))).join(','))
  return [header, ...body].join('\r\n')
}

/** Trigger a client-side download of `csv` under `filename`. Prepends a UTF-8 BOM so
 *  Excel opens non-ASCII text correctly. No-op outside a browser (guards SSR/tests). */
export function downloadCsv(filename: string, csv: string): void {
  if (typeof document === 'undefined') return
  // BOM as an explicit code point (U+FEFF) rather than an invisible literal in source.
  const bom = String.fromCharCode(0xfeff)
  const blob = new Blob([bom + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.csv') ? filename : filename + '.csv'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** Turn an upload filename into a safe export name with a chosen extension: drop the
 *  original extension, sanitize odd characters, append an optional suffix.
 *  `exportFilename('sales data.xlsx', '-cleaned', 'parquet')` -> `sales_data-cleaned.parquet`.
 *  Falls back to `export` when no base is given. */
export function exportFilename(base: string | null, suffix: string, ext: string): string {
  const stem = (base ?? 'export').replace(/\.[^.]+$/, '').replace(/[^\w.-]+/g, '_') || 'export'
  return `${stem}${suffix}.${ext}`
}

/** Back-compat CSV-name helper (delegates to exportFilename with a `.csv` extension). */
export function csvFilename(base: string | null, suffix = ''): string {
  return exportFilename(base, suffix, 'csv')
}

/** Build a pretty-printed JSON array of row objects, keys ordered by `columns` so the
 *  file mirrors the table's column order (not each object's insertion order). NULL /
 *  undefined cells become JSON null. */
export function toJson(columns: DataColumn[], rows: Record<string, unknown>[]): string {
  const names = columns.map((c) => c.name)
  const ordered = rows.map((row) => {
    const o: Record<string, unknown> = {}
    for (const n of names) o[n] = row[n] ?? null
    return o
  })
  return JSON.stringify(ordered, null, 2)
}

/** Build a TSV string (tab-separated, newline-delimited rows) for clipboard paste into
 *  a spreadsheet. Tabs/newlines inside a value are collapsed to spaces so the pasted
 *  grid keeps its shape. */
export function toTsv(columns: DataColumn[], rows: Record<string, unknown>[]): string {
  const names = columns.map((c) => c.name)
  const clean = (v: unknown): string => cellToString(v).replace(/[\t\r\n]+/g, ' ')
  const header = names.map(clean).join('\t')
  const body = rows.map((row) => names.map((n) => clean(row[n])).join('\t'))
  return [header, ...body].join('\n')
}

/** Trigger a client-side download of raw `blob` under exactly `filename` (no extension
 *  munging -- the caller supplies the full name). Used for server-encoded Excel/Parquet
 *  bytes and for client-built JSON. No-op outside a browser (guards SSR/tests). */
export function downloadBlob(filename: string, blob: Blob): void {
  if (typeof document === 'undefined') return
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** Download a text payload (e.g. JSON) as `filename`. */
export function downloadText(filename: string, text: string, mime = 'application/json'): void {
  downloadBlob(filename, new Blob([text], { type: `${mime};charset=utf-8;` }))
}

/** Copy `text` to the clipboard. Resolves false (never throws) if the platform blocks
 *  it, so the caller can show a toast instead of crashing. Falls back to a hidden
 *  <textarea> + execCommand for non-secure contexts / older browsers. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fall through to the legacy path
  }
  try {
    if (typeof document === 'undefined') return false
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    ta.remove()
    return ok
  } catch {
    return false
  }
}
