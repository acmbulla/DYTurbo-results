#!/usr/bin/env python3

import os
import re
import sys
import array
from collections import defaultdict

import ROOT


def normalize_var(v):

    return (
        v.lower()
        .replace("(l)", "")
        .replace(" ", "")
    )


def clean_var_name(name):

    for suffix in ["lo", "hi"]:

        if name.endswith(suffix):
            name = name[:-len(suffix)]

    return normalize_var(name)


def sanitize(s):

    return (
        str(s)
        .replace(".", "p")
        .replace("-", "m")
        .replace("(", "")
        .replace(")", "")
        .replace("/", "_")
    )


# =====================================================
# parse filename
# =====================================================

def parse_filename(filename):

    base = os.path.basename(filename)
    base = base.replace(".txt", "")

    tokens = base.split("_")

    process = tokens[0]

    # -------------------------------------------------
    # find perturbative order
    # -------------------------------------------------

    order_idx = None

    for i, t in enumerate(tokens):

        if t in ["LO", "NLO", "NNLO", "NLL", "NNLL", "N3LL"]:

            order_idx = i
            break

    if order_idx is None:

        raise RuntimeError(
            f"Could not determine perturbative order in {filename}"
        )

    # -------------------------------------------------
    # parse variables encoded in filename
    # -------------------------------------------------

    variables = []

    i = 1

    while i < order_idx:

        var = normalize_var(tokens[i])

        variables.append(var)

        i += 3

    # -------------------------------------------------
    # order
    # -------------------------------------------------

    order = tokens[order_idx]

    # -------------------------------------------------
    # scales
    # -------------------------------------------------

    scales = {}

    for tok in tokens[order_idx + 1:]:

        m = re.match(
            r"([a-zA-Z]+)([-+]?[0-9]*\.?[0-9]+)",
            tok
        )

        if m:

            scales[m.group(1)] = float(m.group(2))

    return {
        "process": process,
        "variables": variables,
        "order": order,
        "scales": scales,
        "filename": filename
    }


# =====================================================
# parse txt content
# =====================================================
# =====================================================
# parse txt content
# =====================================================

def read_result(filename):

    with open(filename) as f:

        lines = [
            l.strip()
            for l in f
            if l.strip()
        ]

    if len(lines) < 2:

        raise RuntimeError(
            f"Empty file: {filename}"
        )

    # -------------------------------------------------
    # header
    # -------------------------------------------------

    header = lines[0]

    if not header.startswith("#"):

        raise RuntimeError(
            f"Missing header in {filename}"
        )

    header_tokens = (
        header
        .replace("#", "")
        .split()
    )

    # -------------------------------------------------
    # infer variables from txt header
    # -------------------------------------------------

    variables = []

    i = 0

    while i < len(header_tokens):

        tok = header_tokens[i]

        tok_clean = tok.lower()

        if tok_clean in ["pdf0", "uncertainty"]:

            break

        if tok_clean.endswith("lo"):

            var = tok_clean[:-2]

            var = (
                var
                .replace("(l)", "")
                .replace(" ", "")
            )

            variables.append(var)

            i += 2

        else:

            i += 1

    # -------------------------------------------------
    # fallback:
    # single-bin files do not store variables
    # in the txt header
    # -------------------------------------------------

    if len(variables) == 0:

        info = parse_filename(filename)

        variables = list(info["variables"])

    print("")
    print("[DEBUG] file =", filename)
    print("[DEBUG] header tokens =", header_tokens)
    print("[DEBUG] parsed variables =", variables)

    # -------------------------------------------------
    # rows
    # -------------------------------------------------

    entries = []

    # ignore final recap line
    for line in lines[1:-1]:

        toks = line.split()

        cursor = 0

        bins = {}

        # =============================================
        # multi-bin case
        # =============================================

        if len(toks) > 2 * len(variables) + 1:

            for var in variables:

                low = float(toks[cursor])
                high = float(toks[cursor + 1])

                bins[var] = (low, high)

                cursor += 2

        # =============================================
        # single-bin case:
        # recover binning from filename
        # =============================================

        else:

            tokens = (
                os.path.basename(filename)
                .replace(".txt", "")
                .split("_")
            )

            print("[DEBUG] filename tokens =", tokens)

            order_idx = None

            for ii, tt in enumerate(tokens):

                if tt in [
                    "LO",
                    "NLO",
                    "NNLO",
                    "NLL",
                    "NNLL",
                    "N3LL"
                ]:

                    order_idx = ii
                    break

            # -----------------------------------------
            # parse:
            #
            # qt_qt0_2
            # ptl_ptl25_26
            # qt_qt0_2_ptl25_26
            # etc
            # -----------------------------------------

            j = 1

            while j < order_idx:

                var = normalize_var(tokens[j])

                bin_token = tokens[j + 1]

                # -------------------------------------
                # parse:
                # qt0
                # ptl25
                # etc
                # -------------------------------------

                m = re.match(
                    r"([a-zA-Z]+)([-+]?[0-9]*\.?[0-9]+)",
                    bin_token
                )

                if not m:

                    raise RuntimeError(
                        f"Could not parse bin token "
                        f"{bin_token} in {filename}"
                    )

                low = float(m.group(2))
                high = float(tokens[j + 2])

                bins[var] = (low, high)

                j += 3

        # =============================================
        # value/error
        # =============================================

        value = float(toks[cursor])
        error = float(toks[cursor + 1])

        entries.append({
            "bins": bins,
            "value": value,
            "error": error
        })

    return entries

# =====================================================
# grouping
# =====================================================

def build_group_key(info):

    return (
        info["process"],
        info["order"],
        tuple(info["variables"])
    )


# =====================================================
# load directory
# =====================================================

def load_directory(directory):

    groups = defaultdict(list)

    for fname in os.listdir(directory):

        if not fname.endswith(".txt"):
            continue

        full = os.path.join(directory, fname)

        info = parse_filename(full)

        file_entries = read_result(full)

        key = build_group_key(info)

        for e in file_entries:

            entry = {
                "bins": e["bins"],
                "value": e["value"],
                "error": e["error"],
                "scales": info["scales"],
                "filename": full
            }

            groups[key].append(entry)

    return groups


# =====================================================
# scale naming
# =====================================================

def build_scale_name(scales):

    nominal = True

    for _, v in scales.items():

        if abs(v - 1.0) > 1e-6:

            nominal = False
            break

    if nominal:
        return "nominal"

    out = []

    for k, v in sorted(scales.items()):

        out.append(
            f"{k}{sanitize(v)}"
        )

    return "_".join(out)


# =====================================================
# build ROOT histograms
# =====================================================

def build_histograms(groups, output_root):

    fout = ROOT.TFile(
        output_root,
        "RECREATE"
    )

    for key, entries in groups.items():

        process, order, variables = key

        ndim = len(variables)

        print("")
        print("=" * 80)
        print(f"[INFO] Building group:")
        print(f"  process   = {process}")
        print(f"  order     = {order}")
        print(f"  variables = {variables}")
        print(f"  ndim      = {ndim}")

        # =================================================
        # split by scale variations
        # =================================================

        scale_groups = defaultdict(list)

        for e in entries:

            scale_name = build_scale_name(
                e["scales"]
            )

            scale_groups[scale_name].append(e)

        # =================================================
        # ROOT directory structure
        # =================================================

        process_dir = fout.GetDirectory(process)

        if not process_dir:
            process_dir = fout.mkdir(process)

        order_dir = process_dir.GetDirectory(order)

        if not order_dir:
            order_dir = process_dir.mkdir(order)

        var_dir_name = "_".join(
            sanitize(v)
            for v in variables
        )

        var_dir = order_dir.GetDirectory(var_dir_name)

        if not var_dir:
            var_dir = order_dir.mkdir(var_dir_name)

        var_dir.cd()

        # =================================================
        # loop on scale variations
        # =================================================

        for scale_name, scale_entries in scale_groups.items():

            print("")
            print(f"[INFO] Creating histogram: {scale_name}")

            # =============================================
            # 1D
            # =============================================

            if ndim == 1:

                xvar = variables[0]

                xedges = set()

                for e in scale_entries:

                    print(f"  bins = {e['bins']}")
                    xl, xh = e["bins"][xvar]

                    xedges.add(xl)
                    xedges.add(xh)

                xedges = sorted(xedges)

                print(f"  xvar  = {xvar}")
                print(f"  edges = {xedges}")

                hist = ROOT.TH1D(
                    scale_name,
                    scale_name,
                    len(xedges)-1,
                    array.array("d", xedges)
                )

                for e in scale_entries:

                    xl, xh = e["bins"][xvar]

                    xc = 0.5 * (xl + xh)

                    ibin = hist.FindBin(xc)

                    hist.SetBinContent(
                        ibin,
                        e["value"]
                    )

                    hist.SetBinError(
                        ibin,
                        e["error"]
                    )

                hist.Write()

            # =============================================
            # 2D
            # =============================================

            elif ndim == 2:

                xvar = variables[0]
                yvar = variables[1]

                xedges = set()
                yedges = set()

                for e in scale_entries:

                    xl, xh = e["bins"][xvar]
                    yl, yh = e["bins"][yvar]

                    xedges.add(xl)
                    xedges.add(xh)

                    yedges.add(yl)
                    yedges.add(yh)

                xedges = sorted(xedges)
                yedges = sorted(yedges)

                print(f"  xvar   = {xvar}")
                print(f"  yvar   = {yvar}")
                print(f"  xedges = {xedges}")
                print(f"  yedges = {yedges}")

                hist = ROOT.TH2D(
                    scale_name,
                    scale_name,
                    len(xedges)-1,
                    array.array("d", xedges),
                    len(yedges)-1,
                    array.array("d", yedges)
                )

                for e in scale_entries:

                    xl, xh = e["bins"][xvar]
                    yl, yh = e["bins"][yvar]

                    xc = 0.5 * (xl + xh)
                    yc = 0.5 * (yl + yh)

                    ibin = hist.FindBin(
                        xc,
                        yc
                    )

                    hist.SetBinContent(
                        ibin,
                        e["value"]
                    )

                    hist.SetBinError(
                        ibin,
                        e["error"]
                    )

                hist.Write()

            # =============================================
            # 3D
            # =============================================

            elif ndim == 3:

                xvar = variables[0]
                yvar = variables[1]
                zvar = variables[2]

                xedges = set()
                yedges = set()
                zedges = set()

                for e in scale_entries:

                    xl, xh = e["bins"][xvar]
                    yl, yh = e["bins"][yvar]
                    zl, zh = e["bins"][zvar]

                    xedges.add(xl)
                    xedges.add(xh)

                    yedges.add(yl)
                    yedges.add(yh)

                    zedges.add(zl)
                    zedges.add(zh)

                xedges = sorted(xedges)
                yedges = sorted(yedges)
                zedges = sorted(zedges)

                print(f"  xvar   = {xvar}")
                print(f"  yvar   = {yvar}")
                print(f"  zvar   = {zvar}")

                hist = ROOT.TH3D(
                    scale_name,
                    scale_name,
                    len(xedges)-1,
                    array.array("d", xedges),
                    len(yedges)-1,
                    array.array("d", yedges),
                    len(zedges)-1,
                    array.array("d", zedges)
                )

                for e in scale_entries:

                    xl, xh = e["bins"][xvar]
                    yl, yh = e["bins"][yvar]
                    zl, zh = e["bins"][zvar]

                    xc = 0.5 * (xl + xh)
                    yc = 0.5 * (yl + yh)
                    zc = 0.5 * (zl + zh)

                    ibin = hist.FindBin(
                        xc,
                        yc,
                        zc
                    )

                    hist.SetBinContent(
                        ibin,
                        e["value"]
                    )

                    hist.SetBinError(
                        ibin,
                        e["error"]
                    )

                hist.Write()

            else:

                print(
                    f"[WARNING] ndim={ndim} > 3 not implemented"
                )

    fout.Close()


# =====================================================
# main
# =====================================================

if __name__ == "__main__":

    if len(sys.argv) < 2:

        print("")
        print("Usage:")
        print("")
        print(
            "python3 merger.py "
            "<input_dir> [output.root]"
        )
        print("")
        exit(1)

    input_dir = sys.argv[1]

    output_root = "results.root"

    if len(sys.argv) > 2:

        output_root = sys.argv[2]

    print("")
    print(f"[INFO] Loading directory: {input_dir}")

    groups = load_directory(input_dir)

    print(f"[INFO] Found {len(groups)} groups")

    build_histograms(
        groups,
        output_root
    )

    print("")
    print(f"[INFO] Written ROOT file: {output_root}")
    print("")