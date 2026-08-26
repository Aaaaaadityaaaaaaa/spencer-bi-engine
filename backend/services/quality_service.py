"""Whole-table data-quality scan for the Table data-prep workspace (TASK-016).

The companion to ``profile_service`` (TASK-015): the profiler answers "what does
THIS column look like?" on demand; this answers "what's wrong with the WHOLE
table?" automatically. It runs a small battery of checks and returns a ranked list
of findings, each carrying the ``OpKind`` a one-click "Fix" should open in the
existing cleaning dialog (the fix itself routes through ``OpDialog``'s dry-run
preview -- this scan never mutates data, bumps a version, or writes history).

Like ``profile_service`` / ``aggregate_service``, every query is built as an **Ibis
expression on an unbound table** and compiled to DuckDB SQL text (Ibis is a compiler
here -- it never opens its own connection), then executed through the existing
``db_manager.run_readwrite`` wrapper. **No column input travels from the client** --
the service enumerates columns from the LIVE schema itself (fresh PRAGMA per request
via the shared ``_columns_of``, never cached), so there is even less client surface
than the profiler (ADR-012 -- no client-assembled SQL). Single-table only (ADR-006);
the router resolves the table.

The whole scan is bounded to at most FOUR queries regardless of table width:
  A) one wide aggregate over ALL columns    -> null% + distinct (empty/constant/high-null)
  B) one wide aggregate over STRING columns -> TRY_CAST-to-date/number + whitespace +
                                               hidden-null sentinels + case-folded distinct +
                                               date-shape counts (mixed formats)
  C) one scalar                             -> distinct-row count (duplicate rows)
  D) one wide aggregate over NUMERIC/DATE   -> negative values + future dates (invalid values)

The per-column metric aliases in A/B are SERVER-generated and identifier-safe
(``c{i}_nn`` ...), never the raw column name, so ``t.aggregate(**aggs)`` is safe even
for a column named ``"2024"`` or ``"order id"``; each alias maps back to ``columns[i]``
by index.
"""

import logging
from typing import Any, Dict, List, Optional

import ibis

from services.duckdb_manager import db_manager
from services.transform_service import _unbound, _columns_of  # noqa: F401 (reused helpers)

logger = logging.getLogger("spencer.quality")

# --- thresholds (module constants so the rules are one place to tune) --------
NULL_WARN = 0.20        # >= this share of nulls (but < 100%) -> a "high_null" finding
CAST_CONFIDENT = 0.95   # >= this share of non-nulls parse as date/number -> "stored as text"
MIXED_LO = 0.10         # some (>= this) but not confident parse -> "mixed_values"
DUP_WARN = 0.05         # >= this share of rows duplicated -> medium (else low)
CATEGORICAL_MAX = 50    # only <= this many distinct values counts as "categorical" (case check)
DATE_SHAPE_MIN = 0.10   # a date-shape must cover >= this share of non-nulls to "be present"
DATEISH_MIN = 0.60      # combined date-shape share to believe a text column holds dates

# Hidden-null sentinels: literal strings that MEAN "missing" but read as present.
# Matched case-insensitively AFTER trimming, so " n/a " and "NA" both count. A truly
# blank / whitespace-only value ("" after trim) is folded into the same finding.
SENTINELS = ["N/A", "NA", "NULL", "NONE", "NIL", "-", "?", "--", ".", "(BLANK)"]

# Two most common date shapes. If a text column shows BOTH with meaningful share it
# mixes formats (e.g. "2026-08-23" ISO vs "23/08/26" slash). RE2 syntax (DuckDB).
_ISO_DATE_RE = r"^\d{4}-\d{1,2}-\d{1,2}$"          # 2026-08-23
_SLASH_DATE_RE = r"^\d{1,4}/\d{1,2}/\d{1,4}$"      # 23/08/26, 8/23/2026, 2026/08/23

# Sort order for the response: most-severe first.
_SEV_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}


class QualityError(Exception):
    """User-input problem (unknown/empty table). The router maps this to HTTP 400,
    not 500 -- it is not a server bug."""


def _as_int(v: Any) -> int:
    """A COUNT/SUM scalar -> int; NULL (empty or all-null aggregate) -> 0."""
    return int(v) if v is not None else 0


def _finding(
    code: str,
    severity: str,
    title: str,
    detail: str,
    *,
    column: Optional[str] = None,
    metric: Optional[float] = None,
    suggested_op: Optional[str] = None,
    suggested_params: Optional[Dict[str, Any]] = None,
    alt_op: Optional[str] = None,
    alt_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one finding dict matching QualityFinding. The id is stable per
    (code, column) so the UI can key/dedupe and it survives re-scans."""
    return {
        "id": f"{code}:{column}" if column is not None else code,
        "code": code,
        "severity": severity,
        "title": title,
        "detail": detail,
        "column": column,
        "metric": metric,
        "suggested_op": suggested_op,
        "suggested_params": suggested_params,
        "alt_op": alt_op,
        "alt_params": alt_params,
    }


async def assess_table(table_name: str) -> Dict[str, Any]:
    """Scan a session table for quality issues. Returns a plain dict matching
    QualityReport. Raises QualityError (-> 400) for an unknown/empty-schema table."""
    columns = await _columns_of(table_name)  # fresh schema, never cached
    if not columns:
        raise QualityError(f"table '{table_name}' has no columns or does not exist")

    t = _unbound(table_name, columns)
    sqls: List[str] = []
    findings: List[Dict[str, Any]] = []

    # --- Query A: total + per-column non-null count & distinct count ---------
    # Generated identifier-safe aliases (never the raw column name) so this is safe
    # for oddly-named columns; read back by insertion order (Ibis preserves it).
    aggsA: Dict[str, Any] = {"total": t.count()}
    for i, (name, _raw) in enumerate(columns):
        col = t[name]
        aggsA[f"c{i}_nn"] = col.count()      # COUNT(col) -> non-null count
        aggsA[f"c{i}_nd"] = col.nunique()    # COUNT(DISTINCT col), NULLs excluded
    sqlA = ibis.to_sql(t.aggregate(**aggsA), dialect="duckdb")
    sqls.append(sqlA)
    rowA = await db_manager.run_readwrite(sqlA)
    statsA = dict(zip(list(aggsA.keys()), rowA[0])) if rowA else {}
    total = _as_int(statsA.get("total"))

    # --- Query B (string columns only, non-empty table): TRY_CAST + whitespace +
    #     hidden-null sentinels + case-folded distinct + date-shape counts. ------
    string_idx: List[int] = [
        i for i, (name, _raw) in enumerate(columns) if t[name].type().is_string()
    ]
    statsB: Dict[str, Any] = {}
    if string_idx and total > 0:
        aggsB: Dict[str, Any] = {}
        for i in string_idx:
            col = t[columns[i][0]]
            trimmed = col.strip()
            # TRY_CAST returns NULL on failure, so COUNT() = # of values that parse.
            aggsB[f"c{i}_num"] = col.try_cast("float64").count()
            aggsB[f"c{i}_dt"] = col.try_cast("date").count()
            # Rows whose value differs from its trimmed form (NULLs contribute 0).
            aggsB[f"c{i}_ws"] = (col != trimmed).sum()
            # Hidden nulls: blank-after-trim OR a known null-token (case-insensitive).
            aggsB[f"c{i}_hn"] = (
                (trimmed == "") | trimmed.upper().isin(SENTINELS)
            ).sum()
            # Case-folded distinct: fewer than the raw distinct => casing variants.
            aggsB[f"c{i}_fd"] = trimmed.lower().nunique()
            # Canonical distinct (TASK-041 #3/#6): fold case, drop punctuation, then
            # collapse internal whitespace -- i.e. exactly what the suggested one-tap
            # normalize produces. Fewer than the case-folded distinct => values that
            # differ only by punctuation/spacing ('u.p.i' vs 'upi'). Kept consistent
            # with the fix so a flagged column genuinely collapses when fixed.
            aggsB[f"c{i}_cd"] = (
                trimmed.lower()
                .re_replace(r"[^a-z0-9 ]", "")
                .re_replace(r"\s+", " ")
                .strip()
                .nunique()
            )
            # Date-shape counts: how many values match each of the two shapes.
            aggsB[f"c{i}_iso"] = col.re_search(_ISO_DATE_RE).sum()
            aggsB[f"c{i}_sl"] = col.re_search(_SLASH_DATE_RE).sum()
        sqlB = ibis.to_sql(t.aggregate(**aggsB), dialect="duckdb")
        sqls.append(sqlB)
        rowB = await db_manager.run_readwrite(sqlB)
        statsB = dict(zip(list(aggsB.keys()), rowB[0])) if rowB else {}

    # --- Query C (non-empty table): duplicate full-row count -----------------
    duplicate_rows = 0
    if total > 0:
        sqlC = ibis.to_sql(t.distinct().count(), dialect="duckdb")
        sqls.append(sqlC)
        rowC = await db_manager.run_readwrite(sqlC)
        distinct_rows = _as_int(rowC[0][0]) if rowC else total
        duplicate_rows = max(0, total - distinct_rows)

    # --- Query D (non-empty table): out-of-range values ("invalid values") ----
    # Numeric columns  -> count of negatives; date/timestamp columns -> count of
    # values dated after "now". These are REVIEW-ONLY signals (no suggested_op):
    # a negative or a future date is often legitimate, so the scan flags but never
    # offers a one-click fix that could destroy real data. `ibis.today()`/`now()`
    # compile to CURRENT_DATE / CURRENT_TIMESTAMP (no literal travels).
    numeric_idx: List[int] = [
        i for i, (name, _raw) in enumerate(columns)
        if t[name].type().is_numeric() and not t[name].type().is_boolean()
    ]
    temporal_idx: List[int] = [
        i for i, (name, _raw) in enumerate(columns)
        if t[name].type().is_date() or t[name].type().is_timestamp()
    ]
    statsD: Dict[str, Any] = {}
    if (numeric_idx or temporal_idx) and total > 0:
        aggsD: Dict[str, Any] = {}
        for i in numeric_idx:
            aggsD[f"c{i}_neg"] = (t[columns[i][0]] < 0).sum()
        for i in temporal_idx:
            col = t[columns[i][0]]
            horizon = ibis.now() if col.type().is_timestamp() else ibis.today()
            aggsD[f"c{i}_fut"] = (col > horizon).sum()
        sqlD = ibis.to_sql(t.aggregate(**aggsD), dialect="duckdb")
        sqls.append(sqlD)
        rowD = await db_manager.run_readwrite(sqlD)
        statsD = dict(zip(list(aggsD.keys()), rowD[0])) if rowD else {}

    # --- Derive findings -----------------------------------------------------
    for i, (name, _raw) in enumerate(columns):
        nn = _as_int(statsA.get(f"c{i}_nn"))
        nd = _as_int(statsA.get(f"c{i}_nd"))
        null_count = max(0, total - nn)
        null_pct = (null_count / total) if total else 0.0

        # Structural axis: at most ONE finding (empty > constant > high_null).
        structural: Optional[str] = None
        if total > 0 and nn == 0:
            structural = "empty_column"
            findings.append(_finding(
                "empty_column", "high",
                f"'{name}' is entirely empty",
                "Every value in this column is null. It carries no information.",
                column=name, metric=100.0, suggested_op="drop_column",
            ))
        elif nn > 0 and nd <= 1:
            structural = "constant"
            findings.append(_finding(
                "constant", "low",
                f"'{name}' has a single value",
                "Every non-null row shares one value, so the column can't distinguish rows.",
                column=name, metric=float(nd), suggested_op="drop_column",
            ))
        elif null_pct >= NULL_WARN:
            structural = "high_null"
            pct = round(null_pct * 100, 2)
            findings.append(_finding(
                "high_null", "medium",
                f"'{name}' is {pct}% missing",
                f"{null_count:,} of {total:,} rows are null. Consider filling or dropping them.",
                column=name, metric=pct, suggested_op="impute_null",
            ))
        elif null_count > 0:
            # TASK-041 #6/#8: sub-threshold missingness. Type-agnostic (evaluated for
            # EVERY column, not just strings), so it survives a cast -- fixing a
            # "stored as text" finding by casting no longer makes the column's missing
            # values silently vanish from the panel (the #8 complaint). Low severity;
            # dismissible via Ignore (#7) when the few nulls are expected.
            structural = "partial_null"
            pct = round(null_pct * 100, 2)
            findings.append(_finding(
                "partial_null", "low",
                f"'{name}' has some missing values",
                f"{null_count:,} of {total:,} rows ({pct}%) are null. Fill or drop them if they matter.",
                column=name, metric=pct, suggested_op="impute_null",
            ))

        # Type/whitespace axis: string columns only, and only when the column is
        # not already empty/constant (those dominate; a constant column's type is moot).
        if i in string_idx and structural not in ("empty_column", "constant") and nn > 0:
            num_ratio = _as_int(statsB.get(f"c{i}_num")) / nn
            dt_ratio = _as_int(statsB.get(f"c{i}_dt")) / nn
            ws = _as_int(statsB.get(f"c{i}_ws"))
            hn = _as_int(statsB.get(f"c{i}_hn"))
            folded_nd = _as_int(statsB.get(f"c{i}_fd"))
            canon_nd = _as_int(statsB.get(f"c{i}_cd"))
            iso_ct = _as_int(statsB.get(f"c{i}_iso"))
            slash_ct = _as_int(statsB.get(f"c{i}_sl"))

            # Date-shape mixing: both shapes present with a meaningful share, and the
            # column is mostly date-shaped -> it holds dates written inconsistently.
            shapes_present = sum(1 for c in (iso_ct, slash_ct) if c / nn >= DATE_SHAPE_MIN)
            dateish = (iso_ct + slash_ct) / nn
            mixed_dates = shapes_present >= 2 and dateish >= DATEISH_MIN

            # Type axis, mutually exclusive (elif). mixed-date is checked FIRST and
            # deliberately outranks text_as_date: DuckDB's TRY_CAST(AS DATE) happily
            # parses BOTH "2026-01-05" and "05/01/26", so a format-mixed column would
            # otherwise look 100%-castable -- but casting it silently guesses DMY vs
            # MDY and can corrupt data. Flag the mix (review-only) instead of a cast.
            # `typed` gates the categorical case check below (casing is moot for these).
            typed = False
            if mixed_dates:
                typed = True
                pct = round(dateish * 100, 2)
                findings.append(_finding(
                    "mixed_date_format", "low",
                    f"'{name}' mixes date formats",
                    f"About {pct}% of values look like dates but in more than one layout "
                    "(e.g. 2026-08-23 vs 23/08/26). Casting now would guess day-vs-month and "
                    "may corrupt values -- standardize the format first.",
                    column=name, metric=pct, suggested_op=None,  # review-only: DMY/MDY is ambiguous
                ))
            elif dt_ratio >= CAST_CONFIDENT:
                typed = True
                pct = round(dt_ratio * 100, 2)
                findings.append(_finding(
                    "text_as_date", "medium",
                    f"'{name}' looks like a date stored as text",
                    f"{pct}% of values parse as a date. Cast the column to DATE to enable date tools.",
                    column=name, metric=pct, suggested_op="cast",
                ))
            elif num_ratio >= CAST_CONFIDENT:
                typed = True
                pct = round(num_ratio * 100, 2)
                findings.append(_finding(
                    "text_as_number", "medium",
                    f"'{name}' looks numeric but is stored as text",
                    f"{pct}% of values parse as a number. Cast the column to a numeric type.",
                    column=name, metric=pct, suggested_op="cast",
                ))
            elif max(num_ratio, dt_ratio) >= MIXED_LO:
                typed = True
                pct = round(max(num_ratio, dt_ratio) * 100, 2)
                # TASK-041 #2: offer a coercing cast toward whichever type most values
                # parse as. Un-parseable values become NULL -- destructive -- so the
                # fix opens the dialog pre-set to coerce and the dry-run preview shows
                # the exact coerced-null count BEFORE anything is applied (the Review
                # Gate protects the user; this scan still never mutates).
                to_date = dt_ratio >= num_ratio
                findings.append(_finding(
                    "mixed_values", "low",
                    f"'{name}' has mixed / inconsistent values",
                    f"About {pct}% of values parse as a number or date and the rest do not "
                    "-- the column mixes types. Coercing to the dominant type sets the "
                    "unparseable rest to null (preview shows how many).",
                    column=name, metric=pct, suggested_op="cast",
                    suggested_params={
                        "coerce": True,
                        "new_type": "DATE" if to_date else "DOUBLE",
                    },
                ))

            if ws > 0:
                findings.append(_finding(
                    "whitespace", "low",
                    f"'{name}' has values with extra whitespace",
                    f"{ws:,} value(s) have leading/trailing whitespace. Trim to avoid split groups.",
                    column=name, metric=float(ws), suggested_op="string_normalize",
                ))

            # Hidden nulls: placeholder tokens that read as present but MEAN missing.
            if hn > 0:
                findings.append(_finding(
                    "hidden_null", "medium",
                    f"'{name}' has values that mean 'missing'",
                    f"{hn:,} value(s) are blank or a placeholder like 'N/A', 'NULL', or '-'. "
                    "Normalize them to real nulls so they count as missing data.",
                    column=name, metric=float(hn), suggested_op="string_normalize",
                ))

            # Inconsistent casing: a low-cardinality (categorical) column whose distinct
            # count shrinks once case/whitespace is folded away -> the "same" category is
            # written several ways. Skipped for numeric/date-ish columns (casing is moot).
            if not typed and 1 < nd <= CATEGORICAL_MAX and folded_nd < nd:
                findings.append(_finding(
                    "inconsistent_case", "medium",
                    f"'{name}' has inconsistent capitalization",
                    f"{nd:,} distinct values collapse to {folded_nd:,} once case and spacing "
                    "are ignored (e.g. 'Male', 'male', 'M ' treated as one). Normalize casing.",
                    column=name, metric=float(nd - folded_nd), suggested_op="string_normalize",
                    suggested_params={"trim": True, "case": "lower"},
                ))

            # Punctuation/spacing variants (TASK-041 #3/#6): distinct count shrinks
            # further once punctuation is dropped and internal spacing collapsed -> the
            # same category is written with different separators ('upi' vs 'u.p.i' vs
            # 'U P I'). Independent of the casing check (both can fire). The suggested
            # one-tap is the exact normalize the canonical-distinct metric mirrors, so
            # the flagged variants genuinely merge when applied.
            if not typed and 1 < folded_nd <= CATEGORICAL_MAX and canon_nd < folded_nd:
                findings.append(_finding(
                    "inconsistent_values", "medium",
                    f"'{name}' has values that differ only by punctuation or spacing",
                    f"{folded_nd:,} values collapse to {canon_nd:,} once punctuation and "
                    "spacing are ignored (e.g. 'u.p.i', 'U.P.I', 'upi' treated as one). "
                    "Normalize them so they group together.",
                    column=name, metric=float(folded_nd - canon_nd),
                    suggested_op="string_normalize",
                    suggested_params={
                        "case": "lower", "strip_special": True, "collapse_whitespace": True,
                    },
                ))

        # Invalid-values axis (REVIEW-ONLY -- no suggested_op, so a legitimate negative
        # or future date is never destroyed by a one-click fix). Numeric -> negatives;
        # date/timestamp -> after-now. Skipped for an all-empty column (count is 0 anyway).
        if i in numeric_idx and structural != "empty_column":
            neg = _as_int(statsD.get(f"c{i}_neg"))
            if neg > 0:
                # TASK-041 #2: offer a one-tap "keep only rows >= 0" filter. The
                # predicate uses the quoted column name (doubled quotes if the name
                # itself contains one) and is re-validated by the shared fail-closed
                # formula validator on apply; the dry-run preview shows the row delta
                # before anything is removed (review-only remains the default stance --
                # this just pre-fills a sensible, reversible fix).
                qname = '"' + name.replace('"', '""') + '"'
                findings.append(_finding(
                    "negative_values", "low",
                    f"'{name}' has negative values",
                    f"{neg:,} value(s) are below zero. If this column can't be negative "
                    "(age, quantity, price), those rows are likely errors. Fix keeps only "
                    "rows where the value is zero or more (preview shows how many drop), "
                    "or 'Make positive' drops the minus sign and keeps every row.",
                    column=name, metric=float(neg), suggested_op="filter_rows",
                    suggested_params={"predicate": f"{qname} >= 0", "action": "keep"},
                    # TASK-042: the second option -- abs() the column in place instead of
                    # dropping rows. Needs only the column (carried on the finding), so no
                    # alt_params. Both fixes go through OpDialog's dry-run preview.
                    alt_op="absolute_value",
                ))
        if i in temporal_idx and structural != "empty_column":
            fut = _as_int(statsD.get(f"c{i}_fut"))
            if fut > 0:
                findings.append(_finding(
                    "future_date", "low",
                    f"'{name}' has dates in the future",
                    f"{fut:,} value(s) are dated after today. Verify these aren't typos "
                    "(e.g. a mistyped year) -- review them.",
                    column=name, metric=float(fut), suggested_op=None,
                ))

    # Table-level: duplicate rows.
    if duplicate_rows > 0:
        dup_ratio = duplicate_rows / total if total else 0.0
        sev = "medium" if dup_ratio >= DUP_WARN else "low"
        findings.append(_finding(
            "duplicate_rows", sev,
            f"{duplicate_rows:,} duplicate row(s)",
            f"{duplicate_rows:,} of {total:,} rows are exact duplicates of another row.",
            column=None, metric=float(duplicate_rows), suggested_op="dedupe",
        ))

    findings.sort(key=lambda f: (_SEV_RANK.get(f["severity"], 9), f["code"], f["column"] or ""))

    logger.debug("quality scan %s: %d finding(s)", table_name, len(findings))
    return {
        "row_count": total,
        "column_count": len(columns),
        "ok": len(findings) == 0,
        "findings": findings,
        "compiled_sql": ";\n\n".join(sqls),
    }
