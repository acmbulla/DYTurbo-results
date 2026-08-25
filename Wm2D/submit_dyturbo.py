#!/usr/bin/env python3

import os
import itertools
import subprocess
import datetime
import argparse

# -------------------------
# CLI
# -------------------------

ALL_TERMS = ["BORN", "CT", "VJREAL", "VJVIRT"]

parser = argparse.ArgumentParser(description="Submit DYTurbo jobs")
parser.add_argument(
    "--terms",
    nargs="+",
    default=["all"],
    choices=ALL_TERMS + ["all"],
    help="Which terms to submit. E.g. --terms BORN CT or --terms all"
)
args = parser.parse_args()

if "all" in args.terms:
    active_terms = ALL_TERMS
else:
    active_terms = args.terms

print("")
print(f"[INFO] Active terms: {active_terms}")

# -------------------------
# user config
# -------------------------

executable = "run_dyturbo.sh"

cwd = os.getcwd()
process = "unknown"

if "DYTurbo-results/" in cwd:
    process = cwd.split("DYTurbo-results/")[1].split("/")[0]

configs = [
    "Template/qt.in",
]

orders = {
    # "NLL":  1,
    "NNLL": 2,
    "N3LL": 3,
}

# =====================================================
# scale variations
# =====================================================

scale_values = [0.5, 1.0, 2.0]

scale_variations = [
    (muR, muF, muQ)
    for muR, muF, muQ in itertools.product(scale_values, scale_values, scale_values)
    if max(muR, muF, muQ) / min(muR, muF, muQ) <= 2
    and (muR, muF, muQ) != (1.0, 1.0, 1.0)
]

# scale_variations = [
#     (1.0, 1.0, 1.0)
# ]

print("")
print(f"[INFO] scale variations: {len(scale_variations)} entries")
for v in scale_variations:
    print(f"  {v}")
print("")

os.makedirs("jobs",    exist_ok=True)
os.makedirs("logs",    exist_ok=True)
os.makedirs("outputs", exist_ok=True)

# =====================================================
# term definitions
#
# each term dict carries the .in switches that
# must be set to True for that term; everything
# else is set to False in modify_config.
# =====================================================

TERM_SWITCHES = {
    "BORN": {
        "doBORN":   "true",
        "doCT":     "false",
        "doVJ":     "false",
        "doVJREAL": "false",
        "doVJVIRT": "false",
    },
    "CT": {
        "doBORN":   "false",
        "doCT":     "true",
        "doVJ":     "false",
        "doVJREAL": "false",
        "doVJVIRT": "false",
    },
    "VJREAL": {
        "doBORN":   "false",
        "doCT":     "false",
        "doVJ":     "true",
        "doVJREAL": "true",
        "doVJVIRT": "false",
    },
    "VJVIRT": {
        "doBORN":   "false",
        "doCT":     "false",
        "doVJ":     "true",
        "doVJREAL": "false",
        "doVJVIRT": "true",
    },
}

# -------------------------
# helper
# -------------------------

def modify_config(
    template,
    output,
    order,
    muR,
    muF,
    muQ,
    tag,
    qt_bins_string,
    ptl_bins_string,
    vegas_params=None
):
    with open(template) as f:
        lines = f.readlines()

    new_lines = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("order"):
            new_lines.append(f"order = {order}\n")
        elif stripped.startswith("kmuren"):
            new_lines.append(f"kmuren = {muR}\n")
        elif stripped.startswith("kmufac"):
            new_lines.append(f"kmufac = {muF}\n")
        elif stripped.startswith("fmures"):
            new_lines.append(f"fmures = {muQ}\n")
        elif stripped.startswith("output_filename"):
            new_lines.append(f"output_filename = outputs/{tag}\n")
        elif stripped.startswith("qt_bins"):
            new_lines.append(f"qt_bins = [ {qt_bins_string} ]\n")
        elif stripped.startswith("ptl_bins"):
            new_lines.append(f"ptl_bins = [ {ptl_bins_string} ]\n")

        # -------------------------------------------------
        # term switches
        # -------------------------------------------------
        elif stripped.startswith("doBORN"):
            new_lines.append(f"doBORN = {vegas_params['doBORN']}\n")
        elif stripped.startswith("doCT"):
            new_lines.append(f"doCT = {vegas_params['doCT']}\n")
        elif stripped.startswith("doVJ") and not stripped.startswith("doVJREAL") and not stripped.startswith("doVJVIRT"):
            new_lines.append(f"doVJ = {vegas_params['doVJ']}\n")
        elif stripped.startswith("doVJREAL"):
            new_lines.append(f"doVJREAL = {vegas_params['doVJREAL']}\n")
        elif stripped.startswith("doVJVIRT"):
            new_lines.append(f"doVJVIRT = {vegas_params['doVJVIRT']}\n")

        # -------------------------------------------------
        # vegas quadrature switches
        # -------------------------------------------------
        elif stripped.startswith("BORNquad"):
            new_lines.append(f"BORNquad = {vegas_params['BORNquad']}\n")
        elif stripped.startswith("CTquad"):
            new_lines.append(f"CTquad = {vegas_params['CTquad']}\n")
        elif stripped.startswith("FPCquad"):
            new_lines.append(f"FPCquad = {vegas_params['FPCquad']}\n")
        elif stripped.startswith("VJquad"):
            new_lines.append(f"VJquad = {vegas_params['VJquad']}\n")

        # -------------------------------------------------
        # vegas ncalls
        # -------------------------------------------------
        elif stripped.startswith("vegasncallsBORN"):
            new_lines.append(f"vegasncallsBORN = {vegas_params['vegasncallsBORN']}\n")
        elif stripped.startswith("vegasncallsCT"):
            new_lines.append(f"vegasncallsCT = {vegas_params['vegasncallsCT']}\n")
        elif stripped.startswith("vegasncallsVJLO"):
            new_lines.append(f"vegasncallsVJLO = {vegas_params['vegasncallsVJLO']}\n")
        elif stripped.startswith("vegasncallsVJREAL"):
            new_lines.append(f"vegasncallsVJREAL = {vegas_params['vegasncallsVJREAL']}\n")
        elif stripped.startswith("vegasncallsVJVIRT"):
            new_lines.append(f"vegasncallsVJVIRT = {vegas_params['vegasncallsVJVIRT']}\n")

        # -------------------------------------------------
        # cuba controls
        # -------------------------------------------------
        elif stripped.startswith("cubanbatch"):
            new_lines.append(f"cubanbatch = {vegas_params['cubanbatch']}\n")
        elif stripped.startswith("maxevalVJREAL"):
            new_lines.append(f"maxevalVJREAL = {vegas_params['maxevalVJREAL']}\n")
        elif stripped.startswith("maxevalVJVIRT"):
            new_lines.append(f"maxevalVJVIRT = {vegas_params['maxevalVJVIRT']}\n")

        # -------------------------------------------------
        # nstart / nincrease  (pathological bin override)
        # -------------------------------------------------
        elif stripped.startswith("nstart"):
            new_lines.append(f"nstart = {vegas_params['nstart']}\n")
        elif stripped.startswith("nincrease"):
            new_lines.append(f"nincrease = {vegas_params['nincrease']}\n")

        # -------------------------------------------------
        # grid / flags
        # -------------------------------------------------
        elif stripped.startswith("statefile"):
            new_lines.append(f"statefile = {vegas_params['statefile']}\n")
        elif stripped.startswith("vegasFlagsExtra"):
            new_lines.append(f"vegasFlagsExtra = {vegas_params['vegasFlagsExtra']}\n")

        else:
            new_lines.append(line)

    with open(output, "w") as f:
        f.writelines(new_lines)


# =====================================================
# adaptive integration configuration
# =====================================================

# empirical critical diagonal:  pTcrit = 45 + 0.6 * qT_high
# delta = ptl_high - pTcrit
#
# nstart override:
#   delta > -5  ->  pathological  ->  nstart = 20M
#   else        ->  normal        ->  nstart =  1M  (DYTurbo default)

NSTART_PATHOLOGICAL = 20_000_000
NSTART_NORMAL       =  1_000_000
NINCREASE_DEFAULT   =  1_000_000


def get_vegas_params(
    qt_low,
    qt_high,
    ptl_low,
    ptl_high,
    order_name,
    process
):
    delta = ptl_high - (45 + 0.6 * qt_high)

    # -------------------------------------------------
    # nstart: high for pathological bins
    # -------------------------------------------------
    if delta > -5:
        nstart = NSTART_PATHOLOGICAL
    else:
        nstart = NSTART_NORMAL

    # -------------------------------------------------
    # defaults
    # -------------------------------------------------
    params = {
        # term switches (overridden per-term later)
        "doBORN":   "true",
        "doCT":     "true",
        "doVJ":     "true",
        "doVJREAL": "true",
        "doVJVIRT": "true",

        # quadrature switches
        "BORNquad": "true",
        "CTquad":   "true",
        "FPCquad":  "true",
        "VJquad":   "false",

        # vegas ncalls
        "vegasncallsBORN":   1000000,
        "vegasncallsCT":     2000000,
        "vegasncallsVJLO":  20000000,
        "vegasncallsVJREAL": 50000000,
        "vegasncallsVJVIRT":  5000000,

        # cuba controls
        "cubanbatch": 10000,

        # nstart / nincrease
        "nstart":    nstart,
        "nincrease": NINCREASE_DEFAULT,
    }

    # -------------------------------------------------
    # SAFE REGION  (delta < -5)
    # -------------------------------------------------
    if delta < -5:
        params.update({
            "BORNquad": "true",
            "CTquad":   "true",
            "FPCquad":  "true",
            "VJquad":   "false",
            "vegasncallsBORN":    1000000,
            "vegasncallsCT":      2000000,
            "vegasncallsVJLO":   20000000,
            "vegasncallsVJREAL": 50000000,
            "vegasncallsVJVIRT":  5000000,
            "cubanbatch": 10000,
        })
        if order_name != "NLL":
            params.update({
                "vegasncallsBORN":    5000000,
                "vegasncallsCT":     10000000,
                "vegasncallsVJLO":  100000000,
                "vegasncallsVJREAL":100000000,
                "vegasncallsVJVIRT": 20000000,
                "cubanbatch": 50000,
            })

    # -------------------------------------------------
    # CRITICAL REGION  (-5 <= delta < 0)
    # -------------------------------------------------
    elif delta < 0:
        params.update({
            "BORNquad": "true",
            "CTquad":   "true",
            "FPCquad":  "true",
            "VJquad":   "false",
            "vegasncallsBORN":   10000000,
            "vegasncallsCT":     20000000,
            "vegasncallsVJLO":  150000000,
            "vegasncallsVJREAL":150000000,
            "vegasncallsVJVIRT": 50000000,
            "cubanbatch": 100000,
        })
        if order_name != "NLL":
            params.update({
                "vegasncallsBORN": 20000000,
                "vegasncallsCT":   50000000,

                "vegasncallsVJLO":   300000000,
                "vegasncallsVJREAL": 300000000,
                "vegasncallsVJVIRT": 100000000,

                "cubanbatch": 100000,
            })

    # -------------------------------------------------
    # PATHOLOGICAL REGION  (0 <= delta < 3)
    # -------------------------------------------------
    elif delta < 3:
        params.update({
            "BORNquad": "false",
            "CTquad":   "false",
            "FPCquad":  "false",
            "VJquad":   "false",
            "vegasncallsBORN":   2000000,
            "vegasncallsCT":     2000000,
            "vegasncallsVJLO":   5000000,
            "vegasncallsVJREAL":10000000,
            "vegasncallsVJVIRT": 5000000,
            "cubanbatch": 5000,
        })
        if order_name != "NLL":
            params.update({
                "vegasncallsBORN":   5000000,
                "vegasncallsCT":     5000000,
                "vegasncallsVJLO":  10000000,
                "vegasncallsVJREAL":20000000,
                "vegasncallsVJVIRT":10000000,
                "cubanbatch": 5000,
            })

    # -------------------------------------------------
    # ULTRA SUPPRESSED  (delta >= 3)
    # -------------------------------------------------
    else:
        params.update({
            "BORNquad": "false",
            "CTquad":   "false",
            "FPCquad":  "false",
            "VJquad":   "false",
            "vegasncallsBORN":   1000000,
            "vegasncallsCT":     1000000,
            "vegasncallsVJLO":   2000000,
            "vegasncallsVJREAL": 5000000,
            "vegasncallsVJVIRT": 2000000,
            "cubanbatch": 2000,
        })
        if order_name != "NLL":
            params.update({
                "vegasncallsBORN":   2000000,
                "vegasncallsCT":     2000000,
                "vegasncallsVJLO":   5000000,
                "vegasncallsVJREAL":10000000,
                "vegasncallsVJVIRT": 5000000,
                "cubanbatch": 2000,
            })

    # -------------------------------------------------
    # HIGH-qT BOOST for V+J Real
    # -------------------------------------------------
    QT_BOOST_THRESHOLD = 0.0
    QT_BOOST_FACTOR      = 250
    VJVIRT_MAXEVAL_FACTOR =  50

    if qt_high > QT_BOOST_THRESHOLD and order_name != "NLL":
        params["vegasncallsVJREAL"] = int(
            params["vegasncallsVJREAL"] * QT_BOOST_FACTOR
        )

    INT32_SAFE_MAX = 2_000_000_000 

    params["maxevalVJREAL"] = params["vegasncallsVJREAL"]
    params["maxevalVJVIRT"] = min(
        int(params["vegasncallsVJVIRT"] * VJVIRT_MAXEVAL_FACTOR),
        INT32_SAFE_MAX,
    )

    return params


# -------------------------
# detect EOS
# -------------------------

cwd = os.getcwd()
on_eos = cwd.startswith("/eos/")
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

if on_eos:
    afs_base      = "/afs/cern.ch/user/a/abulla/private/LOG1/jobs/DYturbo"
    tarball_dest  = "/eos/user/a/abulla/CMSSW_14_0_21/src/dyturbo-1.4.2-empire.tar.gz"
    tarball_source = "/eos/user/a/abulla/CMSSW_14_0_21/src"
else:
    afs_base      = "/gwpool/users/abulla/private/jobs/DYturbo"
    tarball_dest  = "/gwpool/users/abulla/DYTurbo/dyturbo-1.4.2-empire.tar.gz"
    tarball_source = "/gwpool/users/abulla/DYTurbo"

workdir  = f"{afs_base}/{process}"
jobs_dir = f"{workdir}/jobs"
logs_dir = f"{workdir}/logs"

os.makedirs(jobs_dir, exist_ok=True)
os.makedirs(logs_dir, exist_ok=True)

# -------------------------
# tar / copy
# -------------------------

print(f"[INFO] Copying tarball: {tarball_dest}")

# subprocess.run([
#     "tar",
#     "-czf",
#     tarball_dest,
#     "--exclude=dyturbo-1.4.2-empire/DYZ",
#     "-C",
#     tarball_source,
#     "dyturbo-1.4.2-empire"
# ], check=True)

subprocess.run([
    "cp", "-f", tarball_dest,
    os.path.dirname(os.path.dirname(jobs_dir))
], check=True)

subprocess.run(["cp", executable, jobs_dir], cwd=os.getcwd(), check=True)

# =====================================================
# main loop
# =====================================================

qt_edges  = list(range(0, 52, 2))
ptl_edges = list(range(28, 62, 2))

queue_entries = []

# for cfg in configs:

#     obs = os.path.basename(cfg).replace(".in", "")

#     qt_group_size = 1

#     # =================================================
#     # qT loop
#     # =================================================

#     for iqt in range(
#         0,
#         len(qt_edges)-1,
#         qt_group_size
#     ):

#         sub_qt_edges = qt_edges[
#             iqt:iqt+qt_group_size+1
#         ]

#         qt_bins_string = " ".join(
#             map(str, sub_qt_edges)
#         )

#         qt_low  = sub_qt_edges[0]
#         qt_high = sub_qt_edges[-1]

#         qt_tag = f"qt{qt_low}_{qt_high}"

#         # =============================================
#         # empirical critical diagonal
#         #
#         # pT_critical ~ 45 + 0.6*qT
#         #
#         # above this:
#         # - cancellations explode
#         # - quadrature dies
#         # - vegas variance explodes
#         # =============================================

#         pt_critical = 45 + 0.6 * qt_high

#         # =============================================
#         # high-qT region
#         #
#         # above ~35 GeV:
#         # no pathological phase-space remains
#         #
#         # merge all pT bins
#         # =============================================

#         # if qt_high >= 35:

#         #     ptl_groups = [ptl_edges]
            
#         # # =============================================
#         # # one bin per job
#         # # =============================================

#         # else:

#         ptl_groups = [
#             ptl_edges[i:i+2]
#             for i in range(len(ptl_edges)-1)
#         ]

#         # =============================================
#         # adaptive low-qT grouping
#         # =============================================

#         # else:

#         #     ptl_groups = []

#         #     ipt = 0

#         #     while ipt < len(ptl_edges)-1:

#         #         ptl_low_tmp = ptl_edges[ipt]

#         #         # -------------------------------------
#         #         # distance from pathological diagonal
#         #         # -------------------------------------

#         #         delta = (
#         #             ptl_low_tmp - pt_critical
#         #         )

#         #         # -------------------------------------
#         #         # adaptive refinement
#         #         # -------------------------------------

#         #         if delta >= 0:

#         #             # pathological
#         #             ptl_group_size = 1

#         #         elif delta >= -5:

#         #             # very delicate
#         #             ptl_group_size = 2

#         #         elif delta >= -10:

#         #             # difficult
#         #             ptl_group_size = 3

#         #         elif delta >= -15:

#         #             # moderate
#         #             ptl_group_size = 5

#         #         elif delta >= -20:

#         #             # safe
#         #             ptl_group_size = 8

#         #         else:

#         #             # very safe
#         #             ptl_group_size = 12

#         #         # -------------------------------------
#         #         # avoid overflow
#         #         # -------------------------------------

#         #         remaining = (
#         #             len(ptl_edges)-1 - ipt
#         #         )

#         #         ptl_group_size = min(
#         #             ptl_group_size,
#         #             remaining
#         #         )

#         #         # -------------------------------------
#         #         # build pT group
#         #         # -------------------------------------

#         #         sub_ptl_edges = ptl_edges[
#         #             ipt:ipt+ptl_group_size+1
#         #         ]

#         #         ptl_groups.append(
#         #             sub_ptl_edges
#         #         )

#         #         ipt += ptl_group_size

#         print("")
#         print(
#             f"[INFO] qT = [{qt_low}, {qt_high}] "
#             f"--> generated {len(ptl_groups)} pT groups"
#         )

#         # =============================================
#         # pT loop
#         # =============================================

#         for sub_ptl_edges in ptl_groups:

#             ptl_bins_string = " ".join(
#                 map(str, sub_ptl_edges)
#             )

#             ptl_low  = sub_ptl_edges[0]
#             ptl_high = sub_ptl_edges[-1]

#             ptl_tag = f"ptl{ptl_low}_{ptl_high}"

#             # =========================================
#             # perturbative orders
#             # =========================================

#             for order_name, order_value in orders.items():

#                 if order_value == 3:

#                     variations = [
#                         (1.0, 1.0, 1.0)
#                     ]

#                 else:

#                     variations = scale_variations

#                 # =====================================
#                 # adaptive vegas setup
#                 # =====================================

#                 vegas_params = get_vegas_params(
#                     qt_low,
#                     qt_high,
#                     ptl_low,
#                     ptl_high,
#                     order_name,
#                     process
#                 )

#                 # =====================================
#                 # scale variations
#                 # =====================================

#                 for muR, muF, muQ in variations:

#                     tag = (
#                         f"{process}_{obs}_"
#                         f"{qt_tag}_"
#                         f"{ptl_tag}_"
#                         f"{order_name}_"
#                         f"muR{muR}_"
#                         f"muF{muF}_"
#                         f"muQ{muQ}"
#                     )

#                     # nome griglia: stesso per nominale e variazioni
#                     # (niente muR/muF/muQ nel nome)
#                     grid_tag = (
#                         f"{process}_{obs}_{qt_tag}_{ptl_tag}_{order_name}"
#                     )
#                     vegas_params["statefile"] = f"grid_{grid_tag}.state"

#                     # flag: 16 = crea/trattieni (nominale),
#                     #       48 = carica solo la griglia, riparti da zero
#                     #            sulle statistiche (variazioni)
#                     is_nominal = (muR, muF, muQ) == (1.0, 1.0, 1.0)
#                     vegas_params["vegasFlagsExtra"] = 16 if is_nominal else 48

#                     cfg_out = (
#                         f"{jobs_dir}/{tag}.in"
#                     )

#                     modify_config(
#                         cfg,
#                         cfg_out,
#                         order_value,
#                         muR,
#                         muF,
#                         muQ,
#                         tag,
#                         qt_bins_string,
#                         ptl_bins_string,
#                         vegas_params
#                     )

#                     queue_entries.append(
#                         f"{jobs_dir}/{tag}"
#                     )


# =============================================
# bin patologici da rifare con nstart=20M
# =============================================

PATHOLOGICAL_BINS = {
    # (0,  2):  list(range(44, 60, 2)),
    # (2,  4):  list(range(46, 60, 2)),
    # (4,  6):  list(range(46, 60, 2)),
    # (6,  8):  list(range(48, 60, 2)),
    # (8,  10): list(range(48, 60, 2)),  # era 50
    # (10, 12): list(range(50, 60, 2)),  # era 52
    # (12, 14): list(range(50, 60, 2)),
    # (14, 16): list(range(52, 60, 2)),  # era 54
    # (16, 18): list(range(54, 60, 2)),  # era 56
    # (18, 20): list(range(54, 60, 2)),  # era 56
    # (20, 22): list(range(54, 60, 2)),  # era 56
    # (22, 24): list(range(56, 60, 2)),  # era 58
    # (24, 26): list(range(58, 60, 2)),  # nuovo
    # (26, 28): list(range(58, 60, 2)),  # nuovo
}

PATHOLOGICAL_BINS = {
    (8,  10): [48],
    (10, 12): [50],
    (12, 14): [50],
    (14, 16): [52,54],
    (16, 18): [52,54],
    (18, 20): [52,54],
    (20, 22): [54],
    (22, 24): [54,56],
    (24, 26): [56,58],
    (26, 28): [58],
    (28, 30): [58],
}

queue_entries = []

for cfg in configs:
    obs = os.path.basename(cfg).replace(".in", "")

    for iqt in range(0, len(qt_edges) - 1):

        qt_low  = qt_edges[iqt]
        qt_high = qt_edges[iqt + 1]
        qt_tag         = f"qt{qt_low}_{qt_high}"
        qt_bins_string = f"{qt_low} {qt_high}"

        ptl_groups = [
            ptl_edges[i:i+2]
            for i in range(len(ptl_edges) - 1)
        ]

        for sub_ptl_edges in ptl_groups:

            ptl_low         = sub_ptl_edges[0]
            ptl_high        = sub_ptl_edges[-1]
            ptl_tag         = f"ptl{ptl_low}_{ptl_high}"
            ptl_bins_string = f"{ptl_low} {ptl_high}"

            delta = ptl_high - (45 + 0.6 * qt_high)

            for order_name, order_value in orders.items():

                if order_value == 3:
                    variations = [(1.0, 1.0, 1.0)]
                else:
                    variations = scale_variations

                # determine which terms are valid for this order
                # NLL has no Real/Virtual split (just VJ)
                if order_value == 1:
                    terms_for_order = [t for t in active_terms if t not in ("VJREAL", "VJVIRT")]
                    # NLL: add VJ as a single term if requested
                    # (handled outside this script for now)
                else:
                    terms_for_order = active_terms

                vegas_params = get_vegas_params(
                    qt_low, qt_high,
                    ptl_low, ptl_high,
                    order_name, process
                )

                for term_name in terms_for_order:

                    # merge term switches into vegas_params
                    vegas_params.update(TERM_SWITCHES[term_name])

                    for muR, muF, muQ in variations:

                        tag = (
                            f"{process}_{obs}_"
                            f"{qt_tag}_"
                            f"{ptl_tag}_"
                            f"{order_name}_"
                            f"_{term_name}_"
                            f"muR{muR}_muF{muF}_muQ{muQ}"
                        )

                        grid_tag = (
                            f"{process}_{obs}_{qt_tag}_{ptl_tag}"
                            f"_{order_name}_{term_name}"
                        )
                        vegas_params["statefile"] = f"grid_{grid_tag}.state"

                        is_nominal = (muR, muF, muQ) == (1.0, 1.0, 1.0)
                        vegas_params["vegasFlagsExtra"] = 16 if is_nominal else 48

                        cfg_out = f"{jobs_dir}/{tag}.in"

                        modify_config(
                            cfg,
                            cfg_out,
                            order_value,
                            muR, muF, muQ,
                            tag,
                            qt_bins_string,
                            ptl_bins_string,
                            vegas_params
                        )

                        queue_entries.append(f"{jobs_dir}/{tag}")

# -------------------------
# condor requirements
# -------------------------

extra_requirements = ""

if not on_eos:
    extra_requirements = """
request_cpus = 1
request_memory = 2048
Requirements = (machine == "hercules02.hcms.it")
"""

# =====================================================
# submit files — split by (order, term)
# =====================================================

for order_name in orders.keys():
    for term_name in active_terms:

        label = f"{order_name}_{term_name}"

        submit = f"""
executable = run_dyturbo.sh

arguments = $(cfg).in

output = /dev/null
error  = /dev/null
log    = /dev/null

getenv = True

should_transfer_files = YES

transfer_input_files = run_dyturbo.sh,$(cfg).in,../../{tarball_dest.split('/')[-1]}

+JobFlavour = "nextweek"

JobBatchName = "DYTurbo_{process}_{label}"

{extra_requirements}

queue cfg in (
"""

        matching = [
            q for q in queue_entries
            if f"_{order_name}_{term_name}_" in q
        ]

        if not matching:
            continue

        submit += "\n".join(matching)
        submit += "\n)\n"

        subfile = f"{jobs_dir}/submit_{label}.jds"

        with open(subfile, "w") as f:
            f.write(submit)

        print(f"[INFO] Created submit file: {subfile}  ({len(matching)} jobs)")

# # =====================================================
# # submit all
# # =====================================================

# for order_name, subfile in submit_files.items():

#     print("")
#     print(
#         f"[INFO] Submitting {order_name}"
#     )

#     subprocess.run(
#         [
#             "condor_submit",
#             os.path.basename(subfile)
#         ],
#         cwd=os.path.dirname(subfile),
#         check=True
#     )

# print("")
# print("[INFO] Submitted all jobs")