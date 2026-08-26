// Turn an internal session table id into the name the user actually recognises
// (the cleaned stem of the file they uploaded). TASK-041 #10.
//
// The backend names every session table `t_<uuid>_<clean_name>`, where <uuid> is a
// uuid4 with its hyphens replaced by underscores (see `_table_name_for` in
// backend/routers/session.py). So `t_e8d29c58_5f1a_4b2c_9d3e_0a1b2c3d4e5f_messy_sales_dataset_100k`
// should read as `messy_sales_dataset_100k` in the UI.
//
// Anchored to the FULL uuid shape so it only ever strips a genuine session prefix — a
// user table whose name merely happens to contain hex is left untouched. Case-insensitive
// for safety, though Python emits lowercase hex.
const SESSION_TABLE_PREFIX = /^t_[0-9a-f]{8}(?:_[0-9a-f]{4}){3}_[0-9a-f]{12}_/i

/**
 * Friendly, human-facing label for a table id. DISPLAY ONLY — never send the result
 * back to the API as a `table_name` (the backend needs the full internal id). Anything
 * that doesn't match the session prefix (or an empty/nullish value) is returned as-is.
 */
export function friendlyTableName(raw: string | null | undefined): string {
  if (!raw) return ''
  const stripped = raw.replace(SESSION_TABLE_PREFIX, '')
  return stripped || raw
}
