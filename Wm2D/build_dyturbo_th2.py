#!/usr/bin/env python3
"""
build_dyturbo_th2.py

Step 2: read DYTurbo log files directly (reusing the parser from
parse_dyturbo_logs.py, no CSV in between -- everything stays as an
in-memory pandas DataFrame) and build 2D (qT, pT(l)) ROOT histograms,
one set per (Resummation, Counter term, V+J Real, V+J Virtual, TOTAL)
contribution, for:
    - value       (the integral itself)
    - error       (its absolute integration error)
    - rel_error   (|error / value|, the one you actually want to look at)
    - chisq_red   (reduced chi-squared = chisq/dof from the last Vegas
                   iteration; None/missing for Gauss quadrature integrals)

One ROOT file is written per (order, muR, muF, muQ) combination found in
the input logs, e.g. "dyturbo_th2_N3LL_muR1.0_muF1.0_muQ1.0.root", each
containing histograms (5 contributions x 4 quantities), named
    h2_value_<contribution>, h2_error_<contribution>,
    h2_relerr_<contribution>, h2_chisqred_<contribution>
with "<contribution>" spaces replaced by underscores (e.g. "V+J_Real"),
PLUS one "error fraction" histogram per non-TOTAL contribution:
    h2_errfrac_<contribution>
giving, bin by bin, what percentage of TOTAL's squared error (variance)
that contribution alone accounts for (e.g. 70 means "this term explains
70% of TOTAL's error in this bin" -- the quickest way to see, across the
whole (qT, pT) grid, which term to improve where).

PLUS one "value fraction" histogram per non-TOTAL contribution:
    h2_valfrac_<contribution>
giving, bin by bin, value_contrib / |value_TOTAL| * 100 (%), WITH sign.
A bin reading +150 means that term contributes +150% of the total (i.e.
there is a large cancellation with other terms). This is the complement
to errfrac: if a term has chisq_red=500 but valfrac=2%, the poorly
converged integral barely affects the total and can be deprioritized;
if valfrac=80% the poor convergence is a real problem.

The qT and pT(l) axes use the REAL (possibly non-uniform) bin edges found
in the logs, not a uniform binning -- built from the sorted, deduplicated
set of bin edges across all files in the group, with a contiguity check
(warns about gaps/overlaps instead of silently misplacing bins).

Usage:
    python3 build_dyturbo_th2.py *.log --outdir th2_out
    python3 build_dyturbo_th2.py /path/to/logs/*.log --outdir th2_out --txt dump.txt
"""

import argparse
import glob
import os
import sys

import pandas as pd
import ROOT
ROOT.gROOT.SetBatch(True)

from parse_dyturbo_logs import load_all

# chisq_red is filled only when Vegas was used (not Gauss quadrature);
# bins where it's missing (NaN) are left at 0 in the histogram.
QUANTITIES = ["value", "error", "rel_error", "chisq_red"]


def safe_name(s):
    return s.replace(" ", "_").replace("+", "p")


def build_edges(df, lo_col, hi_col, label):
    """Build a sorted array of bin edges from the unique (lo, hi) pairs in
    df[lo_col]/df[hi_col], checking that bins tile contiguously (each
    bin's hi == the next bin's lo). Returns (edges_list, lo_to_index_dict)
    where lo_to_index_dict maps a lo-edge value to its 1-based ROOT bin
    index."""
    pairs = sorted(df[[lo_col, hi_col]].drop_duplicates().itertuples(index=False, name=None))
    if not pairs:
        raise ValueError(f"no {label} bins found")

    for i in range(len(pairs) - 1):
        if abs(pairs[i][1] - pairs[i + 1][0]) > 1e-6:
            print(f"[warn] {label} binning is not contiguous: bin {pairs[i]} "
                  f"is followed by {pairs[i + 1]} (gap/overlap of "
                  f"{pairs[i + 1][0] - pairs[i][1]:.4g}); histogram bins will "
                  f"still be built back-to-back, but the x-axis values won't "
                  f"exactly reflect this gap")

    edges = [pairs[0][0]] + [p[1] for p in pairs]
    lo_to_index = {p[0]: i + 1 for i, p in enumerate(pairs)}  # 1-based ROOT bin index
    return edges, lo_to_index


def make_th2(name, title, xedges, yedges):
    nx, ny = len(xedges) - 1, len(yedges) - 1
    h = ROOT.TH2D(name, title, nx, array_d(xedges), ny, array_d(yedges))
    h.GetXaxis().SetTitle("q_{T} [GeV]")
    h.GetYaxis().SetTitle("p_{T}(l) [GeV]")
    return h


def array_d(values):
    from array import array
    return array("d", [float(v) for v in values])


def build_error_breakdown(df_group, qt_edges, qt_lo_to_ix, pt_edges, pt_lo_to_iy,
                           contributions_breakdown):
    """For each (qT, pT) bin, compute what fraction (in %) of the TOTAL
    squared error (variance) each individual contribution -- everything
    except 'TOTAL' itself -- accounts for. E.g. if V+J Real's error alone
    explains 70% of the variance of TOTAL's error in a given bin, its
    histogram will read 70 there.

    Returns {contribution: TH2D}, one histogram per non-TOTAL contribution,
    values in percent (0-100). Bins where the total variance is zero (e.g.
    missing data) are left at 0 in all histograms."""
    hists = {
        c: make_th2(f"h2_errfrac_{safe_name(c)}",
                    f"{c} error fraction of TOTAL variance (%);q_{{T}} [GeV];p_{{T}}(l) [GeV]",
                    qt_edges, pt_edges)
        for c in contributions_breakdown
    }

    pivot = df_group[df_group["contribution"].isin(contributions_breakdown)].pivot_table(
        index=["qt_lo", "pt_lo"], columns="contribution", values="error"
    )

    for (qt_lo, pt_lo), row in pivot.iterrows():
        if qt_lo not in qt_lo_to_ix or pt_lo not in pt_lo_to_iy:
            continue
        ix = qt_lo_to_ix[qt_lo]
        iy = pt_lo_to_iy[pt_lo]

        variances = {
            c: row[c] ** 2
            for c in contributions_breakdown
            if c in row.index and pd.notna(row[c])
        }
        var_tot = sum(variances.values())
        if var_tot <= 0:
            continue
        for c, v in variances.items():
            hists[c].SetBinContent(ix, iy, 100.0 * v / var_tot)

    return hists


def build_value_fraction(df_group, qt_edges, qt_lo_to_ix, pt_edges, pt_lo_to_iy,
                          contributions_breakdown):
    """For each (qT, pT) bin, compute value_contrib / |value_TOTAL| * 100 (%),
    WITH sign, for each non-TOTAL contribution.

    Sign convention:
      +100% means the term equals the total (no cancellation)
      +150% means a positive term that is 1.5x the total (large cancellation
             with a negative term somewhere else)
      -80%  means a negative term that is 0.8x |total| in magnitude

    Bins where value_TOTAL == 0 (or missing) are left at 0.

    Returns {contribution: TH2D}.
    """
    hists = {
        c: make_th2(f"h2_valfrac_{safe_name(c)}",
                    f"{c} value fraction of TOTAL (%);q_{{T}} [GeV];p_{{T}}(l) [GeV]",
                    qt_edges, pt_edges)
        for c in contributions_breakdown
    }

    # pivot on value: rows = (qt_lo, pt_lo), columns = contribution
    all_contribs = contributions_breakdown + ["TOTAL"]
    pivot = df_group[df_group["contribution"].isin(all_contribs)].pivot_table(
        index=["qt_lo", "pt_lo"], columns="contribution", values="value"
    )

    for (qt_lo, pt_lo), row in pivot.iterrows():
        if qt_lo not in qt_lo_to_ix or pt_lo not in pt_lo_to_iy:
            continue
        if "TOTAL" not in row.index or pd.isna(row["TOTAL"]) or row["TOTAL"] == 0:
            continue
        ix = qt_lo_to_ix[qt_lo]
        iy = pt_lo_to_iy[pt_lo]
        total = row["TOTAL"]
        for c in contributions_breakdown:
            if c in row.index and pd.notna(row[c]):
                hists[c].SetBinContent(ix, iy, 100.0 * row[c] / abs(total))

    return hists


def build_group_root_file(df_group, order, muR, muF, muQ, outdir):
    qt_edges, qt_lo_to_ix = build_edges(df_group, "qt_lo", "qt_hi", "qT")
    pt_edges, pt_lo_to_iy = build_edges(df_group, "pt_lo", "pt_hi", "pT(l)")

    fname = f"dyturbo_th2_{order}_muR{muR:g}_muF{muF:g}_muQ{muQ:g}.root"
    fpath = os.path.join(outdir, fname)
    f = ROOT.TFile.Open(fpath, "RECREATE")
    f.cd()

    n_filled_total = 0
    n_expected_total = 0

    contributions = sorted(df_group["contribution"].unique())
    for contrib in contributions:
        tag = safe_name(contrib)

        # -------------------------------------------------------
        # value / error / rel_error histograms (always present)
        # -------------------------------------------------------
        hists = {
            "value": make_th2(
                f"h2_value_{tag}",
                f"{contrib} value;q_{{T}} [GeV];p_{{T}}(l) [GeV]",
                qt_edges, pt_edges),
            "error": make_th2(
                f"h2_error_{tag}",
                f"{contrib} abs. error;q_{{T}} [GeV];p_{{T}}(l) [GeV]",
                qt_edges, pt_edges),
            "rel_error": make_th2(
                f"h2_relerr_{tag}",
                f"{contrib} rel. error;q_{{T}} [GeV];p_{{T}}(l) [GeV]",
                qt_edges, pt_edges),
            # -------------------------------------------------------
            # reduced chi-squared from the last Vegas iteration.
            # Only filled when Vegas was used (chisq_red is not NaN).
            # Gauss quadrature contributions (Resummation in most
            # configs) will simply be left at 0 everywhere.
            # -------------------------------------------------------
            "chisq_red": make_th2(
                f"h2_chisqred_{tag}",
                f"{contrib} reduced #chi^{{2}} (last Vegas iter.);q_{{T}} [GeV];p_{{T}}(l) [GeV]",
                qt_edges, pt_edges),
        }

        sub = df_group[df_group["contribution"] == contrib]
        n_expected = (len(qt_edges) - 1) * (len(pt_edges) - 1)
        n_expected_total += n_expected
        filled = 0

        for row in sub.itertuples(index=False):
            if row.qt_lo not in qt_lo_to_ix or row.pt_lo not in pt_lo_to_iy:
                continue
            ix = qt_lo_to_ix[row.qt_lo]
            iy = pt_lo_to_iy[row.pt_lo]

            hists["value"].SetBinContent(ix, iy, row.value)
            hists["value"].SetBinError(ix, iy, row.error)
            hists["error"].SetBinContent(ix, iy, row.error)
            hists["rel_error"].SetBinContent(ix, iy, row.rel_error)

            # chisq_red is None/NaN for Gauss quadrature integrals
            if pd.notna(row.chisq_red):
                hists["chisq_red"].SetBinContent(ix, iy, row.chisq_red)

            filled += 1

        n_filled_total += filled

        if filled != n_expected:
            print(f"[warn] {fname}: contribution '{contrib}' has {filled}/{n_expected} "
                  f"(qT, pT) cells filled -- missing log files for the rest "
                  f"(those bins are left at 0)")

        for h in hists.values():
            h.Write()

    # -----------------------------------------------------------
    # error-fraction breakdown (one histogram per non-TOTAL term)
    # h2_errfrac_X: what % of TOTAL's variance comes from term X
    # -----------------------------------------------------------
    contributions_breakdown = [c for c in contributions if c != "TOTAL"]
    if len(contributions_breakdown) >= 2:
        breakdown_hists = build_error_breakdown(
            df_group, qt_edges, qt_lo_to_ix, pt_edges, pt_lo_to_iy,
            contributions_breakdown
        )
        for h in breakdown_hists.values():
            h.Write()
    else:
        print(f"[warn] {fname}: fewer than 2 non-TOTAL contributions found, "
              f"skipping error-fraction breakdown (nothing to break down)")

    # -----------------------------------------------------------
    # value-fraction breakdown (one histogram per non-TOTAL term)
    # h2_valfrac_X: value_X / |value_TOTAL| * 100%, with sign.
    # Use together with h2_chisqred_X to judge whether a poorly
    # converged term actually matters for the total result.
    # -----------------------------------------------------------
    if "TOTAL" in contributions and len(contributions_breakdown) >= 1:
        valfrac_hists = build_value_fraction(
            df_group, qt_edges, qt_lo_to_ix, pt_edges, pt_lo_to_iy,
            contributions_breakdown
        )
        for h in valfrac_hists.values():
            h.Write()
    else:
        print(f"[warn] {fname}: TOTAL contribution not found, "
              f"skipping value-fraction breakdown")

    f.Close()
    print(f"Wrote {fpath}  ({n_filled_total}/{n_expected_total} cells filled "
          f"across all contributions)")
    return fpath


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+", help="log file path(s) or glob pattern(s)")
    p.add_argument("--outdir", default="th2_out", help="output directory for the ROOT files")
    p.add_argument("--txt", default=None,
                    help="optionally also dump the parsed long-format table as plain "
                         "whitespace-aligned text (no CSV), for manual inspection")
    p.add_argument("--quiet", action="store_true", help="suppress per-file parser warnings")
    args = p.parse_args()

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

    if args.txt:
        with open(args.txt, "w") as ftxt:
            ftxt.write(df.to_string(index=False))
        print(f"Dumped parsed table (plain text) to {args.txt}")

    os.makedirs(args.outdir, exist_ok=True)

    n_missing_meta = df[["order", "muR", "muF", "muQ"]].isna().any(axis=1).sum()
    if n_missing_meta:
        print(f"[warn] {n_missing_meta} row(s) have no order/muR/muF/muQ "
              f"(filename didn't match the expected convention) and will be "
              f"skipped for the ROOT grouping")
        df = df.dropna(subset=["order", "muR", "muF", "muQ"])

    written = []
    group_cols = ["order", "muR", "muF", "muQ"]
    for (order, muR, muF, muQ), df_group in df.groupby(group_cols):
        try:
            path = build_group_root_file(df_group, order, muR, muF, muQ, args.outdir)
            written.append(path)
        except ValueError as e:
            print(f"[warn] skipping group order={order} muR={muR} muF={muF} "
                  f"muQ={muQ}: {e}")

    print(f"\nDone: {len(written)} ROOT file(s) written to '{args.outdir}/'.")


if __name__ == "__main__":
    main()