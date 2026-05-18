#!/usr/bin/env python3

import os
import re
import sys
import array
from collections import defaultdict

import ROOT


# =====================================================
# helpers
# =====================================================

def normalize_var(v):

    v = (
        v.lower()
        .replace("(l)", "")
        .replace(" ", "")
    )

    aliases = {

        "pt": "ptl",
        "ptlep": "ptl",
        "qt": "qt",
        "yll": "y",
    }

    return aliases.get(v, v)


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

    orders = ["LO", "NLO", "NNLO", "NLL", "NNLL", "N3LL"]

    order_idx = None

    for i, t in enumerate(tokens):
        if t in orders:
            order_idx = i
            break

    if order_idx is None:
        raise RuntimeError(
            f"Could not determine order in {filename}"
        )

    bins = {}
    variables = []

    i = 1

    while i < order_idx:

        # Case A:
        #   qt qt0 2
        #   ptl ptl25 37
        if i + 2 < order_idx:

            var_candidate = normalize_var(tokens[i])
            low_token = tokens[i + 1]
            high_token = tokens[i + 2]

            m = re.match(
                r"([a-zA-Z]+)([-+]?[0-9]*\.?[0-9]+)$",
                low_token
            )

            if m:
                low_var = normalize_var(m.group(1))

                if low_var == var_candidate:
                    bins[var_candidate] = (
                        float(m.group(2)),
                        float(high_token)
                    )
                    variables.append(var_candidate)
                    i += 3
                    continue

        # Case B:
        #   qt0 2
        #   ptl54 55
        if i + 1 < order_idx:

            low_token = tokens[i]
            high_token = tokens[i + 1]

            m = re.match(
                r"([a-zA-Z]+)([-+]?[0-9]*\.?[0-9]+)$",
                low_token
            )

            if m:
                var = normalize_var(m.group(1))

                bins[var] = (
                    float(m.group(2)),
                    float(high_token)
                )
                variables.append(var)
                i += 2
                continue

        raise RuntimeError(
            f"Could not parse bin tokens around "
            f"{tokens[i:order_idx]} in {filename}"
        )

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
        "bins": bins,
        "order": tokens[order_idx],
        "scales": scales,
        "filename": filename
    }


# =====================================================
# parse txt file
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

    # =================================================
    # filename = global truth
    # =================================================

    info = parse_filename(filename)

    filename_bins = dict(info["bins"])

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

    # =================================================
    # variables stored INSIDE txt
    #
    # examples:
    #
    # #qTlo qThi pT(l)lo pT(l)hi PDF0 uncertainty
    #
    # -> txt variables = [qt, ptl]
    #
    # OR
    #
    # #pT(l)lo pT(l)hi PDF0 uncertainty
    #
    # -> txt variables = [ptl]
    #
    # OR
    #
    # #PDF0 uncertainty
    #
    # -> txt variables = []
    # =================================================

    txt_variables = []

    i = 0

    while i < len(header_tokens):

        tok = header_tokens[i]

        tok_clean = tok.lower()

        if tok_clean in ["pdf0", "uncertainty"]:

            break

        if tok_clean.endswith("lo"):

            var = clean_var_name(tok_clean)

            txt_variables.append(var)

            i += 2

        else:

            i += 1

    print("")
    print("=" * 80)
    print(f"[DEBUG] file = {filename}")
    print(f"[DEBUG] header tokens = {header_tokens}")
    print(f"[DEBUG] txt variables = {txt_variables}")
    print(f"[DEBUG] filename bins = {filename_bins}")

    # =================================================
    # rows
    # =================================================

    entries = []

    # ignore final recap line
    for line in lines[1:-1]:

        toks = line.split()

        cursor = 0

        # ---------------------------------------------
        # start from filename bins
        # ---------------------------------------------

        bins = dict(filename_bins)

        # ---------------------------------------------
        # override variables present in txt
        # ---------------------------------------------

        for var in txt_variables:

            low = float(toks[cursor])
            high = float(toks[cursor + 1])

            bins[var] = (low, high)

            cursor += 2

        # ---------------------------------------------
        # value/error
        # ---------------------------------------------

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
        print(f"[INFO] Building group")
        print(f"  process   = {process}")
        print(f"  order     = {order}")
        print(f"  variables = {variables}")
        print(f"  ndim      = {ndim}")

        # =================================================
        # split by scale variation
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

            # =================================================
            # 1D
            # =================================================

            if ndim == 1:

                xvar = variables[0]

                xedges = set()

                for e in scale_entries:

                    xl, xh = e["bins"][xvar]

                    xedges.add(xl)
                    xedges.add(xh)

                xedges = sorted(xedges)

                print(f"  xvar   = {xvar}")
                print(f"  xedges = {xedges}")

                hist = ROOT.TH1D(
                    scale_name,
                    scale_name,
                    len(xedges)-1,
                    array.array("d", xedges)
                )

                hist.Sumw2()

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

            # =================================================
            # 2D
            # =================================================

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

                hist.Sumw2()

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

                # ---------------------------------------------
                # write full 2D histogram
                # ---------------------------------------------

                hist.Write()

                # =================================================
                # projections
                # =================================================

                # ---------------------------------------------
                # integrate over Y
                #
                # -> X distribution
                # ---------------------------------------------

                proj_x = hist.ProjectionX(
                    f"{scale_name}_proj_{xvar}"
                )

                proj_x.SetTitle(
                    f"{scale_name}_proj_{xvar}"
                )

                proj_x.Write()

                # ---------------------------------------------
                # integrate over X
                #
                # -> Y distribution
                # ---------------------------------------------

                proj_y = hist.ProjectionY(
                    f"{scale_name}_proj_{yvar}"
                )

                proj_y.SetTitle(
                    f"{scale_name}_proj_{yvar}"
                )

                proj_y.Write()

            # =================================================
            # 3D
            # =================================================

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

                hist.Sumw2()

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

                # ---------------------------------------------
                # write full 3D histogram
                # ---------------------------------------------

                hist.Write()

                # =================================================
                # 2D projections
                # =================================================

                proj_xy = hist.Project3D(
                    f"xy"
                )

                proj_xy.SetName(
                    f"{scale_name}_proj_{xvar}_{yvar}"
                )

                proj_xy.Write()

                proj_xz = hist.Project3D(
                    f"xz"
                )

                proj_xz.SetName(
                    f"{scale_name}_proj_{xvar}_{zvar}"
                )

                proj_xz.Write()

                proj_yz = hist.Project3D(
                    f"yz"
                )

                proj_yz.SetName(
                    f"{scale_name}_proj_{yvar}_{zvar}"
                )

                proj_yz.Write()

            else:

                print(
                    f"[WARNING] ndim={ndim} not implemented"
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