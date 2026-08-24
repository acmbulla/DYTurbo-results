#!/usr/bin/env python3
"""
parse_dyturbo_logs.py

Step 1: read DYTurbo integration log files (2D qT / pT(l) scan, N3LL/NLL
etc.) and turn them into a single flat (long-format) table with one row per
(file, pT(l) bin, contribution), ready to be pivoted into 2D (qT, pT) maps
in a later step (relative-error heatmaps).

Each log contains one fixed qT bin (given in the "Constant boundaries"
section) and a table with one row per pT(l) bin, with 5 columns:
    Resummation, Counter term, V+J Real, V+J Virtual, TOTAL
Each cell prints "value ± error (time mi)" (mi = minutes of CPU/wall time),
often preceded by a long Vegas iteration dump (for V+J Real / V+J Virtual)
that has to be skipped -- only the final formatted result matters.

Also extracts the reduced chi-squared (chisq/dof) from the last Vegas
iteration line for each cell, when available (Vegas-integrated contributions
only -- Gauss quadrature contributions produce NaN for this column).

Usage:
    python3 parse_dyturbo_logs.py *.log --csv results.csv
    python3 parse_dyturbo_logs.py /path/to/logs/*N3LL*.log --csv n3ll.csv
"""

import argparse
import glob
import os
import re
import sys

import pandas as pd

CONTRIBUTIONS = ["Resummation", "Counter term", "V+J Real", "V+J Virtual", "TOTAL"]


def parse_header_columns(text):
    """Read the actual column names from the table header (between the top
    '┏...┓' border and the first '┣...┫' separator). Returns a list of
    contribution names (e.g. ['Resummation', 'Counter term', 'V+J',
    'TOTAL'] for NLL, which has no Real/Virtual split -- as opposed to
    N3LL's 5 columns), or None if the header can't be found/parsed.

    The leading 'pT(l)' cell (present only in the multi-row table format,
    not in the single-bin format) is dropped automatically if present.
    """
    top = text.find("┏")
    if top == -1:
        return None
    sep = text.find("┣", top)
    if sep == -1:
        return None
    header_block = text[top:sep]
    for line in header_block.split("\n"):
        if "┃" in line and any(c.isalpha() for c in line):
            cells = [c.strip() for c in line.split("┃") if c.strip()]
            if cells and cells[0] == "pT(l)":
                cells = cells[1:]
            return cells if cells else None
    return None


# one finalized dyturbo result cell, e.g. "  -0.8 ±    7.1        ( 3.9mi)"
# or "  3.2795 ± 0.0026        (   44s)" or "   6.919 ±  0.078        (39.1hr)"
# -- DYTurbo prints the time in seconds ('s') for <1 minute, minutes ('mi')
# otherwise, and hours ('hr') for long integrations. Both value and error
# are matched; the time is normalized to minutes downstream.
#
# Very small/large numbers can also share a single power-of-ten factor
# written in Unicode superscript, e.g. "-0 ±   0.22 ·10⁻¹⁸ (4.63mi)" --
# that optional "·10<superscript exponent>" group applies to BOTH value
# and error (it's a shared multiplier, not per-number scientific notation).
RESULT_RE = re.compile(
    r"([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*±\s*(\d+\.?\d*(?:[eE][-+]?\d+)?)"
    r"(?:\s*·10([⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+))?\s*"
    r"\(\s*(\d+\.?\d*)\s*(s|mi|hr)\s*\)"
)

# Vegas iteration chi-squared line, e.g. "chisq 142.827 (9 df)"
CHISQ_RE = re.compile(r"chisq\s+([\d\.eE+\-]+)\s*\((\d+)\s*df\)")

SUPERSCRIPT_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")


def superscript_to_int(s):
    """Convert a Unicode superscript exponent string (e.g. '⁻¹⁸') to an
    int (-18), or None if s is empty/None (no shared exponent present)."""
    if not s:
        return None
    return int(s.translate(SUPERSCRIPT_MAP))


def parse_last_chisq(cell_text):
    """Extract reduced chi-squared (chisq/dof) from the last Vegas
    iteration line found in cell_text. Returns None if not found
    (e.g. Gauss quadrature, not Vegas) or if dof == 0 (first iteration
    always has 0 df and is skipped)."""
    matches = CHISQ_RE.findall(cell_text)
    if not matches:
        return None
    # walk backwards to find the last one with dof > 0
    for chisq_str, dof_str in reversed(matches):
        dof = int(dof_str)
        if dof > 0:
            return float(chisq_str) / dof
    return None


NAN_INF_RE = re.compile(r"\b(nan|inf|-inf|-nan)\b", re.IGNORECASE)


def diagnose_row_mismatch(row_text, n_found, n_expected):
    """Best-effort explanation for why a row didn't produce exactly
    n_expected results, to avoid having to hunt through the raw log by
    hand every time."""
    hints = []
    nan_inf_hits = NAN_INF_RE.findall(row_text)
    if nan_inf_hits:
        hints.append(f"found {len(nan_inf_hits)} occurrence(s) of "
                      f"nan/inf in this row's text (a Vegas integration "
                      f"likely failed/diverged for one column) -> "
                      f"{sorted(set(h.lower() for h in nan_inf_hits))}")
    if not hints:
        hints.append("no obvious cause found automatically (no nan/inf); "
                      "the result line for one column may use a formatting "
                      "this parser doesn't expect -- worth pasting the raw "
                      "row text for this bin so the regex can be extended")
    return hints


def debug_dump_row_matches(row_text, context=25):
    """Print every RESULT_RE match found in a row, with surrounding raw
    text context, so mis-aligned/spurious matches (a match that 'steals'
    the wrong number) can be spotted visually instead of guessed at."""
    for i, m in enumerate(RESULT_RE.finditer(row_text)):
        lo = max(0, m.start() - context)
        hi = min(len(row_text), m.end() + context)
        before = row_text[lo:m.start()].replace("\n", "\\n")
        matched = row_text[m.start():m.end()].replace("\n", "\\n")
        after = row_text[m.end():hi].replace("\n", "\\n")
        exp_str = f" x10^{superscript_to_int(m.group(3))}" if m.group(3) else ""
        print(f"  match #{i}: value={m.group(1)} error={m.group(2)}{exp_str} "
              f"time={m.group(4)}{m.group(5)}")
        print(f"            ...{before}[[{matched}]]{after}...")


def debug_file(path, pt_lo=None, pt_hi=None):
    """Standalone debug entry point: parse one file and dump the raw
    match-by-match breakdown for every row (or just the one matching
    pt_lo/pt_hi if given)."""
    with open(path, "r", errors="replace") as f:
        text = f.read()
    rows = split_rows(text)
    if not rows:
        print(f"No pT(l) rows found in {path}")
        return
    for row_pt_lo, row_pt_hi, row_text in rows:
        if pt_lo is not None and (abs(row_pt_lo - pt_lo) > 1e-6 or abs(row_pt_hi - pt_hi) > 1e-6):
            continue
        n = len(RESULT_RE.findall(row_text))
        print(f"\n=== pT(l) bin [{row_pt_lo}, {row_pt_hi}]: {n} match(es) "
              f"(expected {len(CONTRIBUTIONS)}) ===")
        debug_dump_row_matches(row_text)


# start of a pT(l) row, e.g. "┃   25 -    26 ┃"
ROW_START_RE = re.compile(
    r"┃\s*(\d+\.?\d*)\s*-\s*(\d+\.?\d*)\s*┃"
)

# "Constant boundaries" block: variable name, then "low = X" then "high = Y"
# on the following line (only whitespace before "high").
QT_BOUNDARY_RE = re.compile(
    r"qT\s+low\s*=\s*([-\d\.]+)\s*\n\s*high\s*=\s*([-\d\.]+)"
)

# pT(l) appears in "Constant boundaries" ONLY when a single pT(l) bin is
# being integrated (no per-row table) -- its presence is what signals the
# single-bin table format handled by extract_single_bin_results().
PT_BOUNDARY_RE = re.compile(
    r"pT\(l\)\s+low\s*=\s*([-\d\.]+)\s*\n\s*high\s*=\s*([-\d\.]+)"
)

# filename convention:
#   testWp2D_2G_qt_qt<qtlo>_<qthi>_ptl<ptlo>_<pthi>_<ORDER>_muR<r>_muF<f>_muQ<q>.log
FILENAME_RE = re.compile(
    r"qt_qt(?P<qt_lo>\d+\.?\d*)_(?P<qt_hi>\d+\.?\d*)_"
    r"ptl(?P<ptl_lo>\d+\.?\d*)_(?P<ptl_hi>\d+\.?\d*)_"
    r"(?P<order>LO|[A-Za-z0-9]+LL)_"
    r"muR(?P<muR>\d+\.?\d*)_muF(?P<muF>\d+\.?\d*)_muQ(?P<muQ>\d+\.?\d*)"
)


def parse_filename(path):
    """Best-effort metadata extraction from the filename (used as a
    fallback / cross-check, not as the primary source of the qT range)."""
    m = FILENAME_RE.search(os.path.basename(path))
    if not m:
        return {}
    d = m.groupdict()
    return {
        "fname_qt_lo": float(d["qt_lo"]), "fname_qt_hi": float(d["qt_hi"]),
        "fname_ptl_lo": float(d["ptl_lo"]), "fname_ptl_hi": float(d["ptl_hi"]),
        "order": d["order"],
        "muR": float(d["muR"]), "muF": float(d["muF"]), "muQ": float(d["muQ"]),
    }


def parse_qt_boundary(text):
    """Read the actual qT bin from the 'Constant boundaries' section of the
    log (authoritative, unlike the filename)."""
    m = QT_BOUNDARY_RE.search(text)
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))


def parse_pt_boundary(text):
    """Read the pT(l) bin from 'Constant boundaries', when present (only
    the single-bin table format has it -- see PT_BOUNDARY_RE)."""
    m = PT_BOUNDARY_RE.search(text)
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))


def extract_table_text(text):
    """Scope a search to just the results table (between the outer box
    borders '┏...┛'), to avoid picking up stray matches from elsewhere in
    the log. Falls back to the whole text if the borders aren't found."""
    start = text.find("┏")
    end = text.rfind("┛")
    if start == -1 or end == -1 or end <= start:
        return text
    return text[start:end + 1]


def _results_with_chisq_from_text(text, n_contrib):
    """Given a block of text containing exactly n_contrib finalized result
    cells (plus possibly Vegas iteration dumps before each), return a list
    of (value_str, error_str, exp_str, time_str, unit, chisq_red_or_None)
    tuples, one per contribution in column order.

    The cell boundary for chisq extraction is: from the end of the
    previous RESULT_RE match (or the start of text) to the end of the
    current RESULT_RE match -- this captures all Vegas iteration lines
    that belong to that cell and nothing from the next one.
    """
    match_iters = list(RESULT_RE.finditer(text))
    if len(match_iters) < n_contrib:
        # not enough matches -- return without chisq
        return [
            (m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), None)
            for m in match_iters
        ]

    # use only the first n_contrib matches (ignore summary duplicate)
    match_iters = match_iters[:n_contrib]
    results = []
    for i, m in enumerate(match_iters):
        start = match_iters[i - 1].end() if i > 0 else 0
        cell_text = text[start:m.end()]
        chisq_red = parse_last_chisq(cell_text)
        results.append((
            m.group(1), m.group(2), m.group(3),
            m.group(4), m.group(5), chisq_red,
        ))
    return results


def extract_single_bin_results(text, n_contrib, warn=True, path=""):
    """For logs where BOTH qT and pT(l) are single fixed bins (no per-row
    pT(l) table): the results table has just one row of n_contrib
    finalized results, immediately followed by a duplicated summary line
    with the same numbers again.

    Returns (pt_lo, pt_hi, results) where results is a list of
    (value_str, error_str, exp_str, time_str, unit, chisq_red_or_None)
    tuples (length == n_contrib), or None if this format isn't detected.
    """
    pt_lo, pt_hi = parse_pt_boundary(text)
    if pt_lo is None:
        return None

    table_text = extract_table_text(text)
    all_match_iters = list(RESULT_RE.finditer(table_text))
    if len(all_match_iters) < n_contrib:
        return None

    if warn and len(all_match_iters) > n_contrib:
        print(f"[info] {path}: single-bin table format detected "
              f"(pT(l) = [{pt_lo}, {pt_hi}] from Constant boundaries); "
              f"using the first {n_contrib} of {len(all_match_iters)} "
              f"matches found (the rest is the duplicated summary line at "
              f"the bottom of the table)")

    # use _results_with_chisq_from_text so we also get chisq_red
    results = _results_with_chisq_from_text(table_text, n_contrib)
    return pt_lo, pt_hi, results


def split_rows(text):
    """Split the log text into (pt_lo, pt_hi, row_text) chunks, one per
    pT(l) row of the results table."""
    matches = list(ROW_START_RE.finditer(text))
    rows = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        pt_lo, pt_hi = float(m.group(1)), float(m.group(2))
        rows.append((pt_lo, pt_hi, text[start:end]))
    return rows


def parse_row_with_chisq(row_text, n_contrib):
    """Extract the n_contrib finalized results from one pT(l) row, together
    with the reduced chi-squared from the last Vegas iteration for each
    cell (None for Gauss quadrature cells).

    Returns a list of (value_str, error_str, exp_str, time_str, unit,
    chisq_red_or_None) tuples, one per contribution in column order.
    Vegas iteration dumps in between are ignored automatically since they
    don't match RESULT_RE (they use '+-', not '±', and have no trailing
    '(...s/mi/hr)').
    """
    return _results_with_chisq_from_text(row_text, n_contrib)


def drop_summary_row(rows, fname_ptl_lo=None, fname_ptl_hi=None):
    """DYTurbo prints one extra row at the end of the table spanning the
    FULL pT(l) range (e.g. [25, 60] when the individual rows are
    [25,26], [26,28], ...) -- an aggregate total, not a real bin.

    Primary check: the last row's [lo, hi] matches the pT(l) range from
    the filename (robust even if some body rows failed to parse and
    shifted their min/max). Falls back to comparing against the actual
    body rows' [min(lo), max(hi)] if the filename range isn't available.

    Returns (rows_without_summary, summary_row_or_None).
    """
    if len(rows) < 2:
        return rows, None

    body, last = rows[:-1], rows[-1]

    if fname_ptl_lo is not None:
        if abs(last[0] - fname_ptl_lo) < 1e-6 and abs(last[1] - fname_ptl_hi) < 1e-6:
            return body, last
        return rows, None

    body_lo = min(r[0] for r in body)
    body_hi = max(r[1] for r in body)
    if abs(last[0] - body_lo) < 1e-6 and abs(last[1] - body_hi) < 1e-6:
        return body, last
    return rows, None


def parse_log_file(path, warn=True):
    """Parse a single DYTurbo log file. Returns a list of row-dicts (long
    format, one dict per (pT bin, contribution)), or [] on failure."""
    with open(path, "r", errors="replace") as f:
        text = f.read()

    meta = parse_filename(path)
    qt_lo, qt_hi = parse_qt_boundary(text)
    if qt_lo is None:
        if "fname_qt_lo" in meta:
            qt_lo, qt_hi = meta["fname_qt_lo"], meta["fname_qt_hi"]
            if warn:
                print(f"[warn] {path}: 'Constant boundaries' qT block not found, "
                      f"falling back to filename-derived qT bin [{qt_lo}, {qt_hi}]")
        else:
            if warn:
                print(f"[warn] {path}: could not determine qT bin from log or "
                      f"filename, skipping file")
            return []
    elif "fname_qt_lo" in meta:
        if abs(qt_lo - meta["fname_qt_lo"]) > 1e-6 or abs(qt_hi - meta["fname_qt_hi"]) > 1e-6:
            if warn:
                print(f"[warn] {path}: qT bin in log [{qt_lo}, {qt_hi}] differs "
                      f"from filename [{meta['fname_qt_lo']}, {meta['fname_qt_hi']}]; "
                      f"using the log (authoritative)")

    contributions = parse_header_columns(text) or CONTRIBUTIONS
    if contributions != CONTRIBUTIONS and warn:
        print(f"[info] {path}: table has {len(contributions)} column(s) "
              f"{contributions} (differs from the default N3LL-style "
              f"{CONTRIBUTIONS} -- e.g. NLL logs merge V+J Real/Virtual "
              f"into a single 'V+J' column)")

    # entries: list of (pt_lo, pt_hi, results, diag_text)
    # results: list of (val, err, exp_s, tmin, tunit, chisq_red) per contribution
    # diag_text: raw text used for nan/inf diagnostics on parse failure
    entries = []

    row_chunks = split_rows(text)
    if row_chunks:
        # normal multi-row table (many pT(l) bins)
        row_chunks, summary_row = drop_summary_row(
            row_chunks, meta.get("fname_ptl_lo"), meta.get("fname_ptl_hi")
        )
        if summary_row is not None and warn:
            s_lo, s_hi, _ = summary_row
            print(f"[info] {path}: skipping summary row [{s_lo}, {s_hi}] "
                  f"(spans the full pT(l) range -- it's the aggregate total row, "
                  f"not a real bin)")
        for pt_lo, pt_hi, row_text in row_chunks:
            entries.append((
                pt_lo, pt_hi,
                parse_row_with_chisq(row_text, len(contributions)),
                row_text,
            ))
    else:
        # no row markers -> maybe a single (qT, pT) bin table
        single = extract_single_bin_results(text, len(contributions), warn=warn, path=path)
        if single is None:
            if warn:
                print(f"[warn] {path}: no pT(l) rows found in the results table, "
                      f"and no single-bin 'pT(l)' boundary found either")
            return []
        pt_lo, pt_hi, results = single
        # results already has chisq_red embedded (from _results_with_chisq_from_text)
        entries.append((pt_lo, pt_hi, results, extract_table_text(text)))

    out = []
    for pt_lo, pt_hi, results, diag_text in entries:
        if len(results) != len(contributions):
            if warn:
                print(f"[warn] {path}: pT(l) bin [{pt_lo}, {pt_hi}] has "
                      f"{len(results)} results instead of {len(contributions)} "
                      f"(expected {contributions}); skipping this row")
                for hint in diagnose_row_mismatch(diag_text, len(results), len(contributions)):
                    print(f"         -> {hint}")
            continue
        for contrib, (val, err, exp_s, tmin, tunit, chisq_red) in zip(contributions, results):
            val, err, tmin = float(val), float(err), float(tmin)
            exp = superscript_to_int(exp_s)
            if exp is not None:
                val *= 10.0 ** exp
                err *= 10.0 ** exp
            if tunit == "s":
                tmin = tmin / 60.0
            elif tunit == "hr":
                tmin = tmin * 60.0
            rel_err = abs(err / val) if val != 0 else 0.0
            if err == 0.0 and warn:
                print(f"[warn] {path}: pT(l) bin [{pt_lo}, {pt_hi}], "
                      f"contribution '{contrib}': parsed error is exactly 0.0 "
                      f"(value={val:g}) -- for a Monte Carlo (Vegas) integration "
                      f"this is almost never a genuine zero uncertainty; check "
                      f"the raw log for this cell (possible failed/degenerate run "
                      f"or a mis-parsed cell)")
            out.append({
                "file": path,
                "order": meta.get("order"),
                "muR": meta.get("muR"), "muF": meta.get("muF"), "muQ": meta.get("muQ"),
                "qt_lo": qt_lo, "qt_hi": qt_hi,
                "pt_lo": pt_lo, "pt_hi": pt_hi,
                "contribution": contrib,
                "value": val, "error": err, "rel_error": rel_err,
                "time_min": tmin,
                "chisq_red": chisq_red,  # None for Gauss quadrature, float for Vegas
            })
    return out


def load_all(files, warn=True):
    all_rows = []
    n_ok, n_fail = 0, 0
    for path in files:
        rows = parse_log_file(path, warn=warn)
        if rows:
            n_ok += 1
            all_rows.extend(rows)
        else:
            n_fail += 1
    print(f"Parsed {n_ok} file(s) successfully, {n_fail} produced no usable rows, "
          f"{len(all_rows)} total (file, pT bin, contribution) entries.")
    return pd.DataFrame(all_rows)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+", help="log file path(s) or glob pattern(s)")
    p.add_argument("--csv", default=None, help="save the combined long-format table to CSV")
    p.add_argument("--quiet", action="store_true", help="suppress per-file warnings")
    p.add_argument("--debug-pt-bin", nargs=2, type=float, default=None,
                    metavar=("PT_LO", "PT_HI"),
                    help="debug mode: for the first file given, dump every raw "
                         "regex match found for this pT(l) bin, with context, "
                         "instead of doing a normal parse run (use this to "
                         "diagnose mis-aligned value/error columns)")
    args = p.parse_args()

    if args.debug_pt_bin is not None:
        debug_file(args.files[0], args.debug_pt_bin[0], args.debug_pt_bin[1])
        return

    # expand any glob patterns that the shell didn't already expand
    files = []
    for f in args.files:
        matches = glob.glob(f)
        files.extend(matches if matches else [f])
    files = sorted(set(files))

    if not files:
        sys.exit("No files found.")

    df = load_all(files, warn=not args.quiet)
    if df.empty:
        sys.exit("Nothing could be parsed from the given files.")

    print()
    print(df.head(15).to_string(index=False))
    print("...")
    print(f"\nColumns: {list(df.columns)}")
    print(f"Contributions found: {sorted(df['contribution'].unique())}")
    print(f"Distinct qT bins: {sorted(df[['qt_lo','qt_hi']].drop_duplicates().values.tolist())}")
    print(f"Distinct orders: {sorted(df['order'].dropna().unique())}")

    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"\nSaved combined long-format table to {args.csv}")


if __name__ == "__main__":
    main()