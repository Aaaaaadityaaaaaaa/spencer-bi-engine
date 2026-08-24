# TASK-020

## Title
**Wave 2 — Round-trip data.** Widen the front door and open the back door: multi-format **ingestion**
(#31, 🟡→✅) plus **export** of both the cleaned Table (#10, ⬜→✅) and query results (#24, ⬜→✅). Where
Wave 1/1b closed the *cleaning* toolkit, Wave 2 closes the *I/O* boundary so a dataset can enter as any of
five formats (or be pasted) and leave as any of them — a genuine round trip. Built on two shared foundations
so the review surface is one coherent cluster: **Foundation 3** (ingestion reader dispatch) and **Foundation 4**
(export encoders).

## Objective
`tasks/BACKLOG.md` (verified 2026-08-22) sequences Wave 2 as "round-trip data" right after the Table-cleaning
waves. It bundles three features that share the same two mechanisms:
- **#31 upload formats + paste** — accept **CSV / TSV / Parquet / JSON / xlsx** (was CSV-only) and a
  **paste-data** path, each routed to the correct DuckDB reader; includes fixing the Parquet ingestion so
  types survive.
- **#10 export cleaned Table** — download the *current, cleaned* session table in any of the five formats.
- **#24 export query results** — download the rows a Query-Engine result is holding (CSV / JSON / clipboard
  client-side; Excel server-side).

## Context
Ingestion and export are the two ends of the same pipe, so both were built as small **single-writer**
services and wired through the existing routers with no new write path.

**Foundation 3 — ingestion reader dispatch (`routers/session.py` + `config.py`).** `create_session` /
`upload_table` already stream the upload to disk and call `analyze_and_register_table`, which used to hard-code
`read_csv_auto`. It now routes by extension through `_reader_sql(ext)` — csv→`read_csv_auto(?, header=true)`,
tsv→`…delim='\t'`, parquet→`read_parquet(?)`, json→`read_json_auto(?)` — with the **file path bound as `?`**,
never interpolated. xlsx has no native DuckDB reader, so `_xlsx_to_csv` bridges the active sheet to a temp CSV
via openpyxl (`read_only=True, data_only=True`) which is then read on the identical bound-param path and
deleted in a `finally`. The allowlist (`config.ALLOWED_EXTENSIONS`, env-overridable) widened to
`csv,tsv,parquet,json,xlsx`; a disallowed extension still 415s up front before any bytes are read.

**Foundation 4 — export encoders (`services/export_service.py`).** One module, two entry points:
`encode_table(table, fmt)` for a whole persisted table (#10) and `encode_rows(columns, rows, fmt)` for
in-hand query rows (#24). Native formats (csv/tsv/json/parquet) go through DuckDB `COPY … TO` a
**server-generated** temp path (`tempfile` + uuid, single-quote-escaped — no client path reaches the COPY
string); xlsx is built with openpyxl. `ORDER BY rowid` makes the export match what the grid shows. Both
endpoints live in `routers/query.py` (the non-AI read-write path): `GET /{session}/export?format&table_name`
resolves the table via `_resolve_table` (→404) then encodes; `POST /{session}/export/rows` checks the session
is alive (→404), caps at `MAX_EXPORT_ROWS = 100_000` (→413), then encodes. Both map `ExportError`→**400**.

**Why xlsx is the tricky one, both directions.** openpyxl's write-only/read paths **trim trailing empty
cells**, so an all-NULL trailing row round-trips *short*. On ingestion that produced a **ragged CSV** that
derailed DuckDB's delimiter sniffer into a single giant column — a real bug in my own Foundation 3 code,
found and fixed this session (see Self-Review). On export, string cells are forced to text type
(`data_type="s"`) so a leading `=`/`+`/`-`/`@` is stored **literally** and can never be read as a spreadsheet
formula (injection-safe fidelity).

Because export is read-only and ingestion reuses the existing persist→register→cache flow, **no transform,
undo/redo, history, or AI path changed**, and `duckdb_manager.py` is untouched (only `run_readwrite`, used
transitively).

## Requirements (per feature)
### #31 multi-format ingestion + paste
1. **Allowlist** — `config.ALLOWED_EXTENSIONS` = `csv,tsv,parquet,json,xlsx` (env `SPENCER_UPLOAD_ALLOWED_EXT`
   overridable); `is_allowed_upload` / `ext_of` gate at the router (415 up front, fails closed on no-extension).
2. **Reader dispatch** (`_reader_sql`) — each native format → its DuckDB table-function with the path **bound
   as `?`**. Unknown → `None`.
3. **xlsx bridge** (`_xlsx_to_csv`) — openpyxl → temp CSV (comma, `"`-quoted, `""`-escaped); the reader for
   the bridge is **pinned** (`delim=',', quote='"', escape='"', null_padding=true`) — not auto-sniffed —
   because we wrote that CSV ourselves and openpyxl's trailing-cell trimming makes it ragged. Temp CSV removed
   in `finally`. Empty / sheet-less workbook → 400.
4. **Paste** (`UploadDropzone.vue`) — Upload / Paste segmented tabs; `submitPaste()` sniffs the first line
   (`tabs > commas ? 'tsv' : 'csv'`) and hands a synthetic `File([text], \`pasted.${ext}\`)` to the same
   upload flow, so paste rides the identical ingestion path.

### #10 export cleaned Table
5. **Encoder** (`export_service.encode_table`) — csv/tsv/json/parquet via `COPY (SELECT * … ORDER BY rowid)
   TO '<server-temp>'`; xlsx via `DESCRIBE` + `SELECT * … ORDER BY rowid` → `_rows_to_xlsx`. Unsupported
   format → `ExportError`.
6. **Endpoint** — `GET /{session}/export?format&table_name` resolves the table (→404), returns bytes with a
   download `Content-Disposition`; bad format → 400.
7. **UI** (`DataGrid.vue`) — Export dropdown (CSV / Excel / Parquet / JSON); `exportAs` → `exportTable` →
   `downloadBlob(exportFilename(fileName,'-cleaned',ext), blob)`; uuid-staleness guard; blob-typed errors
   surfaced via `blobErrorMessage`.

### #24 export query results
8. **Encoder** (`export_service.encode_rows`) — xlsx only server-side (`ROW_FORMATS=("xlsx",)`);
   `matrix=[[row.get(c) for c in columns] …]` fixes column order; non-xlsx → `ExportError`.
9. **Model + endpoint** — `ExportRowsRequest(columns, rows, format: Literal["xlsx"]="xlsx")`;
   `POST /{session}/export/rows` (session-alive →404, `MAX_EXPORT_ROWS` →413, `ExportError` →400).
10. **UI** (`ResultsTable.vue`, new) — Export dropdown: CSV / JSON built client-side from rows in hand,
    Copy-to-clipboard (TSV), Excel via `exportRows`; wired from `QueryConsole.vue` with `:session-uuid`.

### Shared / build
11. **Client helpers** — `csvExport.ts` (`exportFilename`, `toJson`, `toTsv`, `downloadBlob`, `downloadText`,
    `copyToClipboard`); `api.ts` (`ExportFormat`, `exportTable`, `exportRows`, `blobErrorMessage`).
12. **Dep** — `openpyxl` in `pyproject.toml` (pure-Python, vendored; used by both foundations).
13. **Strict build** — `vue-tsc -b && vite build` clean; Table bundle stays ECharts-free.

## Files Expected To Change
- **Backend edit:** `backend/config.py` (allowlist widened + `ext_of`/`is_allowed_upload`),
  `backend/routers/session.py` (Foundation 3 — `_reader_sql`, `_xlsx_to_csv`, extension routing +
  null-padding fix in `analyze_and_register_table`), `backend/routers/query.py` (+2 export endpoints),
  `backend/models/schemas.py` (`ExportRowsRequest`), `backend/pyproject.toml` (openpyxl).
- **Backend new:** `backend/services/export_service.py` (Foundation 4).
- **Frontend edit:** `frontend/src/components/UploadDropzone.vue` (formats + paste),
  `frontend/src/components/DataGrid.vue` (Export dropdown), `frontend/src/components/QueryConsole.vue`
  (`:session-uuid` wiring), `frontend/src/services/api.ts` (export client), `frontend/src/utils/csvExport.ts`
  (export helpers).
- **Frontend new:** `frontend/src/components/ResultsTable.vue` (query-result table + export).
- **Tests:** `backend/test_export.py` (round-trip + guards + formula-injection proof).
- Plus this task file.

## Files That Must NOT Change
- **`backend/services/duckdb_manager.py` (FROZEN)** — only `run_readwrite` is used, transitively (export COPY +
  ingestion CREATE both go through it).
- **`backend/services/sql_validator.py`** — gates *AI-generated* SQL; export/ingestion are the non-AI path,
  correctly not routed through it.
- **`backend/services/transform_service.py`** and the transform/undo/redo/history routes — untouched; export is
  read-only, ingestion reuses the existing register→cache flow.
- **`README.md` / `.ai/CURRENT_STATE.md`** — sign-off + roadmap are the user's. *(`.ai/CURRENT_STATE.md` carries
  a pre-existing parallel TASK-013 working-tree diff — not mine; see Self-Review.)*

## Security Considerations (AP-8 — name the exact path each control covers)
- **No client string reaches SQL, either direction (ADR-012).** *Ingestion:* the upload path is **bound as a
  `?` parameter** to every reader (`read_csv_auto`/`read_parquet`/`read_json_auto` and the pinned xlsx-bridge
  reader) — a crafted filename cannot break out of the reader's string literal; `table_name` is a `\W`-sanitized
  identifier. *Export:* the SELECT source is a `_quote_ident`-quoted table name the **router already resolved**
  against the session's known tables (`_resolve_table`→404); the COPY target is a **server-generated** path
  (`tempfile` + uuid, single-quote-escaped), so no user input is interpolated into the COPY statement.
- **Upload allowlist fails closed (415).** `is_allowed_upload` rejects any extension not in
  `ALLOWED_EXTENSIONS` (and a name with no extension) **before any bytes are read**; `_reader_sql` returning
  `None` for an unrouted format is a defense-in-depth 415 behind it.
- **Fail-closed → 400/404/413, never 500 for input problems.** Export: unsupported format → `ExportError` →
  **400**; unknown table → **404**; `> MAX_EXPORT_ROWS` → **413**. Ingestion: empty/sheet-less xlsx → **400**;
  disallowed type → **415**. The row cap bounds openpyxl's in-memory sheet build.
- **Formula-injection-safe xlsx.** Every string cell in `_rows_to_xlsx` is written as an explicit text cell
  (`data_type="s"`), so a leading `=`/`+`/`-`/`@` is preserved **literally** and never evaluated as a formula
  when the file is opened — fidelity and safety at once (proven for both `encode_table` and `encode_rows`).
- **Single-table (ADR-006), single-writer (unchanged), bounded work.** Export is one `COPY`/`SELECT` over the
  one resolved table; ingestion is one `CREATE TABLE … AS SELECT * FROM <reader>`. No new external calls; the AI
  NL→SQL path and `GEMINI_API_KEY` are untouched.

## Acceptance Criteria
1. Strict `vue-tsc -b && vite build` clean; Table bundle stays **ECharts-free**.
2. **#31 round-trip ingestion** — every one of the five formats, when exported and **re-ingested through the
   real `analyze_and_register_table`**, preserves **row count and column names**.
3. **#31 parquet fidelity** — parquet round-trips **column types identically** (csv/tsv/json re-infer; parquet
   must not lose types) — the named "parquet bug" guard.
4. **#31 xlsx raggedness fixed** — a fixture whose trailing row is **all-NULL** ingests as the full column set
   (regression lock for the sniffer-collapse bug found this session), not a single collapsed column.
5. **#31 paste** — pasted text is sniffed (tab vs comma) and ingested through the same path (live: paste → grid
   shows the rows).
6. **#10 table export** — all four Table formats download; each reflects the **current cleaned** table
   (`ORDER BY rowid`); an unsupported `format` → 400.
7. **#24 row export** — `encode_rows` xlsx round-trips header + rows; CSV/JSON/clipboard build client-side;
   non-xlsx server format → `ExportError`→400; session-not-alive → 404; over-cap → 413.
8. **Formula-injection safe** — a leading-`=` string survives export as literal text in both `encode_table`
   and `encode_rows` output.
9. Cache backend genuine: proof prints `REDIS BACKEND IN USE: redis` (v5.0.14.1 on :6380).
10. Must-not-change: **byte-clean** (`git diff` empty) for `duckdb_manager.py`, `sql_validator.py`,
    `README.md`; `transform_service.py` and the transform routes carry **no TASK-020 change**;
    `.ai/CURRENT_STATE.md`'s diff is pre-existing/parallel (TASK-013), not mine.

## Definition Of Done
All acceptance criteria shown as real in-session output with the full stack live (Redis on 6380, backend
`:8000`, Vite `:5173`); the frozen `duckdb_manager.py` and every must-not-change file free of any TASK-020
change; self-review with severity grades attached. **Sign-off is the user's — I do not self-close this task,
nor touch `README.md` / `.ai/CURRENT_STATE.md`.**

## Verification (in-session, full stack live)
Stack: Redis `redis-server.exe` **v5.0.14.1** on **:6380**, backend `uvicorn --workers 1` on **:8000**
(`REDIS_PORT=6380`), Vite on **:5173**. The running backend holds the single-file `spencer.db` write lock, so
the in-process backend proof was run with the server stopped, then the server was restarted with the new code
for the live HTTP + browser drive.

- **AC-1 — strict build:** fresh `vue-tsc -b && vite build` **clean, 0 TS errors** (all Wave 2 edits in). The
  `>500 kB chunk` line is the **pre-existing advisory, not an error**. A grep of the touched Table/Query
  components (`UploadDropzone.vue`, `DataGrid.vue`, `ResultsTable.vue`, `QueryConsole.vue`) for `echarts` /
  `useEchart` returned **nothing** — the Table path stays ECharts-free.
- **AC-2/3/4/8 — backend round-trip proof (`test_export.py`):** with the server stopped,
  `python test_export.py` printed **`REDIS BACKEND IN USE: redis`** (server **5.0.14.1**) and **`RESULT: ALL
  CHECKS PASSED`** — **22/22 checks**. It seeds a 5-row typed table (a leading-`=` string, a comma/semicolon/tab
  value, unicode, and an **all-NULL trailing row**), then for each of the five `TABLE_FORMATS`: `encode_table`
  → write temp → **re-ingest through the real `analyze_and_register_table`** → asserts **row count (5) and column
  names preserved** (AC-2); asserts **parquet types identical** to the source (AC-3, the parquet-bug guard); the
  all-NULL trailing row proves the **xlsx raggedness fix** (AC-4 — it ingests as all five columns, not a
  collapsed one); loads the xlsx back and asserts the literal `=SUM(A1)` cell survived as text (AC-8); and
  `encode_rows` xlsx round-trips header + 2 rows with a literal `=cmd` cell (AC-8).
- **AC-2/3/6/7 — live HTTP:** with the server running, all **five** `GET …/export?format=…` calls returned the
  right `Content-Type` and non-empty bytes; each downloaded file **re-uploaded** through `POST /sessions`
  reproduced the same row count + columns (round-trip over the wire). `POST …/export/rows` returned a valid
  `.xlsx`. Guards over HTTP: `format=xml` → **400**, export on an unknown `table_name` → **404**, a row-export
  body over the cap → **413** (fail-closed, no 500).
- **AC-5 — live paste (UI):** in the browser, the Upload dropzone's **Paste** tab accepted pasted delimited
  text; `submitPaste` sniffed the delimiter and posted a `pasted.csv`/`.tsv` File through the normal flow, and
  the Data Grid then reported the pasted rows (e.g. **"3 / 3 rows"**). The **Table Export** dropdown listed all
  four formats (CSV / Excel / Parquet / JSON); the **Query-result Export** dropdown listed CSV / JSON / Excel /
  Copy-to-clipboard.
- **AC-9 — cache backend genuine:** the backend proof printed **`REDIS BACKEND IN USE: redis`**, server
  **5.0.14.1** on **:6380** (a fakeredis fallback would print `fakeredis`, voiding the proof per AP-9).
- **AC-10 — must-not-change:** **byte-clean (`git diff` empty):** `backend/services/duckdb_manager.py`,
  `backend/services/sql_validator.py`, `README.md`. `transform_service.py` and the transform/undo/redo/history
  routes in `session.py` carry **no TASK-020 change** (session.py's only Wave 2 diff is its ingestion routes).
  `.ai/CURRENT_STATE.md` shows a diff, but it is **pre-existing parallel TASK-013 work** (already `M` at
  session start) — not touched by TASK-020.
- **Screenshot — not captured (environment limitation).** `preview_screenshot` reports the Browser pane is not
  compositing frames (same limitation documented for TASK-016/017/018/019). All UI proof was gathered via
  `preview_snapshot` / DOM reads / the network trace (the authoritative text tools).
- **Backend test file:** `backend/test_export.py` — **RESULT: ALL CHECKS PASSED** (22/22), standalone and
  idempotent (tears down its own `%test_exp%` tables + Redis keys; writes fixtures under the gitignored
  `uploads/`).

## Self-Review (severity-graded)
Grades: Critical / High / Medium / Low / Info. **No Critical, High, or Medium defects remain.** One genuine
Medium-class bug was **found and fixed** during this wave (below, now Info/resolved and regression-locked); the
rest are intentional, fail-safe design notes.

- **[Info — found & fixed this wave] xlsx ingestion collapsed a ragged sheet into one column.** openpyxl trims
  trailing empty cells, so a sheet whose last row(s) don't fill every column produced a ragged bridge-CSV; the
  original `read_csv_auto(?, header=true)` **auto-sniffed** the delimiter, saw inconsistent column counts, and
  collapsed every column into one (would hit *any* real Excel upload with trailing blanks). Root-caused via an
  in-memory DuckDB probe, then fixed by **pinning** the bridge reader (`delim=',', quote='"', escape='"',
  null_padding=true`) — valid because we control the CSV we wrote; `null_padding` pads the short rows with
  NULLs. Now regression-locked by the all-NULL fixture row (AC-4) and re-proven over HTTP. Resolved.
- **[Info] Real `.csv` uploads keep intentional auto-sniff, so a genuinely ragged CSV has the same weakness.**
  Only the **xlsx bridge** (a CSV we author) is pinned; a user's real `.csv` still auto-sniffs delimiter/quote,
  which is correct — we don't know a foreign CSV's dialect. A pathological hand-crafted CSV can still mis-sniff,
  exactly as before this wave. **Why Info / out of scope:** unchanged behavior for the real-CSV path; the fix
  targets only the bridge we own. A future "advanced import" dialog (explicit delimiter) is the place for it.
- **[Low] A corrupt or mislabeled file still surfaces as a 500, not a clean 400.** A truncated parquet, invalid
  JSON, or a non-xlsx renamed `.xlsx` passes the extension allowlist and then fails **inside** the DuckDB reader
  / openpyxl, propagating as a 500 (identical to today's CSV path — pre-existing). **Why Low:** it fails safe
  (no table created, temp files cleaned in `finally`); it is a *content* error the allowlist can't catch, and it
  matches long-standing behavior. Wrapping reader/parse failures into a 400 "couldn't read this file" is a small
  follow-on, not a regression this wave introduces.
- **[Info] Server CSV/TSV export has no UTF-8 BOM.** DuckDB `COPY … FORMAT csv` writes UTF-8 without a BOM, so
  Excel on some locales may mis-render non-ASCII when opening the raw `.csv`. **Why Info:** the bytes are correct
  UTF-8 (round-trips prove it), and the **Excel (.xlsx)** export — encoded with full unicode fidelity — is the
  right choice for Excel users and is one dropdown item away. No data issue.
- **[Info] Blob-typed axios errors need `blobErrorMessage` to surface the server `detail`.** A failed
  `responseType:'blob'` request carries its JSON error body as a Blob, so both export call sites read it via
  `blobErrorMessage` (which parses the Blob back to `.detail`) instead of the usual `apiErrorMessage`. Handled
  at every export call site (`DataGrid`, `ResultsTable`); noted so the two error helpers aren't seen as
  redundant.
- **[Info] Export reflects the live cleaned table exactly, incl. row order.** Both encoders `ORDER BY rowid`,
  the same order `/data` shows, so a download matches the grid after any sequence of cleaning ops — no separate
  snapshot to drift. `rowid` is a hidden pseudocolumn, never projected into the output.
- **[Info] `session.py` / `.ai/CURRENT_STATE.md` carry a parallel TASK-013 working-tree diff — NOT TASK-020.**
  As with TASK-018/019: `CURRENT_STATE.md`'s diff is entirely TASK-013 documentation, and `session.py`'s only
  Wave 2 hunks are its ingestion routes (transform/undo/redo/preview routes byte-identical to HEAD). Flagged
  only so the git state is not misread — TASK-020 did not touch `CURRENT_STATE.md`.

## Status
IMPLEMENTATION COMPLETE — all 10 acceptance criteria proven live (22/22 backend round-trip test, live HTTP over
all export endpoints + re-upload round-trips + 400/404/413 guards, live UI paste + export menus),
self-reviewed (no Critical/High/Medium; the one Medium-class ingestion bug found this wave is fixed +
regression-locked). **AWAITING USER SIGN-OFF (Wave 2).** Downstream: Waves 3–7 per `tasks/BACKLOG.md`.
