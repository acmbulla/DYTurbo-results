#!/usr/bin/env python3

import argparse
from array import array
import ROOT

ROOT.gROOT.SetBatch(True)


VARIABLE_LABELS = {
    "qt":  "q_{T} [GeV]",
    "ptl": "p_{T}^{l} [GeV]",
    "mll": "m_{ll} [GeV]"
}


def read_table(filename):

    bins = []
    vals = []
    errs = []

    with open(filename) as f:

        for line in f:

            line = line.strip()

            if not line or line.startswith("#"):
                continue

            cols = line.split()

            low  = float(cols[0])
            high = float(cols[1])
            val  = float(cols[2])
            err  = float(cols[3])

            # skip total / recap row
            if bins and low == bins[0][0] and high == bins[-1][1]:
                print(f"[INFO] Skipping total row: {low} {high}")
                continue

            bins.append((low, high))
            vals.append(val)
            errs.append(err)

    return bins, vals, errs


def make_histogram(
    bins,
    vals,
    errs,
    variable="qt",
    hist_name="xsec",
    normalise_by_bin_width=False
):

    edges = [b[0] for b in bins]
    edges.append(bins[-1][1])

    h = ROOT.TH1D(
        hist_name,
        hist_name,
        len(bins),
        array('d', edges)
    )

    for i, ((low, high), val, err) in enumerate(
        zip(bins, vals, errs),
        start=1
    ):

        width = high - low

        if normalise_by_bin_width:
            val /= width
            err /= width

        h.SetBinContent(i, val)
        h.SetBinError(i, err)

    # -------------------------
    # axis labels
    # -------------------------

    xlab = VARIABLE_LABELS.get(variable, variable)

    if normalise_by_bin_width:
        ylab = f"d#sigma/d{xlab.split()[0]} [fb/GeV]"
    else:
        ylab = "#sigma [fb]"

    h.GetXaxis().SetTitle(xlab)
    h.GetYaxis().SetTitle(ylab)

    return h


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input table"
    )

    parser.add_argument(
        "--hist-name",
        default="xsec",
        help="Histogram name"
    )

    parser.add_argument(
        "--var",
        choices=["qt", "ptl", "etal"],
        required=True,
        help="Observable"
    )

    parser.add_argument(
        "--norm-width",
        action="store_true",
        help="Normalise by bin width"
    )

    args = parser.parse_args()

    bins, vals, errs = read_table(args.input)

    h = make_histogram(
        bins,
        vals,
        errs,
        variable=args.var,
        hist_name=args.hist_name,
        normalise_by_bin_width=args.norm_width
    )

    fout = ROOT.TFile(args.input.replace(".txt", ".root"), "RECREATE")
    h.Write()
    fout.Close()

    print(f"[INFO] Histogram saved to {args.input.replace('.txt', '.root')}")