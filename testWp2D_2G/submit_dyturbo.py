#!/usr/bin/env python3

import os
import itertools
import subprocess
import datetime

# -------------------------
# user config
# -------------------------

executable = "run_dyturbo.sh"

configs = [
    "Template/qt.in",
    # "Template/ptl.in",
    # "Template/etal.in",
]

orders = {
    "NLL": 1,
    # "NNLL": 2,
    "N3LL": 3,
}

# =====================================================
# scale variations
# =====================================================

scale_values = [0.5, 1.0, 2.0]

# -----------------------------------------------------
# all combinations:
#
# muR, muF, muQ
#
# including:
# 222
# 050505
# 052
# 205
# etc
# -----------------------------------------------------

scale_variations = list(
    itertools.product(
        scale_values,
        scale_values,
        scale_values
    )
)

# optional:
# keep nominal first
scale_variations.sort(
    key=lambda x: (
        x != (1.0, 1.0, 1.0),
        x
    )
)

scale_variations = [
    (1.0, 1.0, 1.0)
]

print("")
print("[INFO] scale variations:")
for v in scale_variations:
    print(v)
print("")


os.makedirs("jobs", exist_ok=True)
os.makedirs("logs", exist_ok=True)
os.makedirs("outputs", exist_ok=True)

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
            new_lines.append(
                f"output_filename = outputs/{tag}\n"
            )
        elif stripped.startswith("qt_bins"):
            new_lines.append(
                f"qt_bins = [ {qt_bins_string} ]\n"
            )
        elif stripped.startswith("ptl_bins"):
            new_lines.append(
                f"ptl_bins = [ {ptl_bins_string} ]\n"
            )
        elif stripped.startswith("BORNquad"):
            new_lines.append(
                f"BORNquad = {vegas_params['BORNquad']}\n"
            )

        elif stripped.startswith("CTquad"):
            new_lines.append(
                f"CTquad = {vegas_params['CTquad']}\n"
            )

        elif stripped.startswith("FPCquad"):
            new_lines.append(
                f"FPCquad = {vegas_params['FPCquad']}\n"
            )

        elif stripped.startswith("VJquad"):
            new_lines.append(
                f"VJquad = {vegas_params['VJquad']}\n"
            )

        elif stripped.startswith("vegasncallsBORN"):
            new_lines.append(
                f"vegasncallsBORN = {vegas_params['vegasncallsBORN']}\n"
            )

        elif stripped.startswith("vegasncallsCT"):
            new_lines.append(
                f"vegasncallsCT = {vegas_params['vegasncallsCT']}\n"
            )

        elif stripped.startswith("vegasncallsVJLO"):
            new_lines.append(
                f"vegasncallsVJLO = {vegas_params['vegasncallsVJLO']}\n"
            )

        elif stripped.startswith("vegasncallsVJREAL"):
            new_lines.append(
                f"vegasncallsVJREAL = {vegas_params['vegasncallsVJREAL']}\n"
            )

        elif stripped.startswith("vegasncallsVJVIRT"):
            new_lines.append(
                f"vegasncallsVJVIRT = {vegas_params['vegasncallsVJVIRT']}\n"
            )

        elif stripped.startswith("cubanbatch"):
            new_lines.append(
                f"cubanbatch = {vegas_params['cubanbatch']}\n"
            )

        else:
            new_lines.append(line)

    with open(output, "w") as f:
        f.writelines(new_lines)

# =========================================================
# adaptive integration configuration
#
# IMPORTANT:
#
# internally DYTurbo recomputes:
#
#   nstart    = vegasncalls / cubacall::nst
#   nincrease = vegasncalls / 10
#
# therefore:
# - we should ONLY tune:
#
#   vegasncalls
#   cubanbatch
#   quadrature switches
#
# and keep:
#
#   cubacall::nst = 5 (src/cubacall.C)
#
# globally in the C++.
# =========================================================

def get_vegas_params(
    qt_low,
    qt_high,
    ptl_low,
    ptl_high,
    order_name
):

    # -----------------------------------------------------
    # empirical suppression frontier
    #
    # above this:
    # - support tiny
    # - cancellations huge
    # - quadrature explodes
    #
    # empirical diagonal:
    #
    # pTcrit ~ 45 + 0.6*qT
    # -----------------------------------------------------

    delta = ptl_high - (45 + 0.6 * qt_high)

    # =====================================================
    # defaults
    # =====================================================

    params = {

        # ---------------------------------------------
        # integration modes
        # ---------------------------------------------

        "BORNquad": "true",
        "CTquad":   "true",
        "FPCquad":  "true",

        "VJquad":   "false",

        # ---------------------------------------------
        # vegas calls
        # ---------------------------------------------

        "vegasncallsBORN": 1000000,
        "vegasncallsCT":   2000000,
        "vegasncallsVJLO": 20000000,
        "vegasncallsVJREAL": 50000000,
        "vegasncallsVJVIRT": 5000000,

        # ---------------------------------------------
        # cuba controls
        # ---------------------------------------------

        "cubanbatch": 10000,
    }

    # =====================================================
    # SAFE REGION
    #
    # well below suppression frontier
    #
    # standard setup works fine
    # =====================================================

    if delta < -5:

        params.update({

            "BORNquad": "true",
            "CTquad":   "true",
            "FPCquad":  "true",

            "VJquad":   "false",

            "vegasncallsBORN": 1000000,
            "vegasncallsCT":   2000000,

            "vegasncallsVJLO":   20000000,
            "vegasncallsVJREAL": 50000000,
            "vegasncallsVJVIRT": 5000000,

            "cubanbatch": 10000,
        })

        # ---------------------------------------------
        # N3LL stabilization
        # ---------------------------------------------

        if order_name == "N3LL":

            params.update({

                "vegasncallsBORN": 5000000,
                "vegasncallsCT":   10000000,

                "vegasncallsVJLO":   100000000,
                "vegasncallsVJREAL": 100000000,
                "vegasncallsVJVIRT": 20000000,

                "cubanbatch": 50000,
            })

    # =====================================================
    # CRITICAL REGION
    #
    # close to suppression frontier
    #
    # here precision really matters
    # =====================================================

    elif delta < 0:

        params.update({

            "BORNquad": "true",
            "CTquad":   "true",
            "FPCquad":  "true",

            "VJquad":   "false",

            "vegasncallsBORN": 10000000,
            "vegasncallsCT":   20000000,

            "vegasncallsVJLO":   150000000,
            "vegasncallsVJREAL": 150000000,
            "vegasncallsVJVIRT": 50000000,

            "cubanbatch": 100000,
        })

        if order_name == "N3LL":

            params.update({

                "vegasncallsBORN": 20000000,
                "vegasncallsCT":   50000000,

                "vegasncallsVJLO":   300000000,
                "vegasncallsVJREAL": 300000000,
                "vegasncallsVJVIRT": 100000000,

                "cubanbatch": 100000,
            })

    # =====================================================
    # PATHOLOGICAL REGION
    #
    # delta > 0
    #
    # strongly suppressed phase space:
    #
    #   qT small
    #   pTl too large
    #
    # observations:
    #
    # - support tiny
    # - cancellations huge
    # - VJREAL dominates runtime
    # - precision requirements LOW
    #
    # strategy:
    #
    # -> full vegas
    # -> aggressively reduce statistics
    # -> prioritize turnaround over precision
    # =====================================================

    # elif delta < 3:

    #     params.update({

    #         # -----------------------------------------
    #         # FULL VEGAS MODE
    #         # -----------------------------------------

    #         "BORNquad": "false",
    #         "CTquad":   "false",
    #         "FPCquad":  "false",

    #         "VJquad":   "false",

    #         # -----------------------------------------
    #         # moderate statistics
    #         # -----------------------------------------

    #         "vegasncallsBORN":   2000000,
    #         "vegasncallsCT":     2000000,

    #         "vegasncallsVJLO":   5000000,
    #         "vegasncallsVJREAL": 10000000,
    #         "vegasncallsVJVIRT": 5000000,

    #         # -----------------------------------------
    #         # smaller batches
    #         # -----------------------------------------

    #         "cubanbatch": 5000,
    #     })

    #     # =================================================
    #     # N3LL
    #     # =================================================

    #     if order_name == "N3LL":

    #         params.update({

    #             # -----------------------------------------
    #             # resummed pieces
    #             # -----------------------------------------

    #             "vegasncallsBORN":   5000000,
    #             "vegasncallsCT":     5000000,

    #             # -----------------------------------------
    #             # V+J
    #             # -----------------------------------------

    #             "vegasncallsVJLO":   10000000,

    #             # REAL dominates runtime
    #             "vegasncallsVJREAL": 20000000,

    #             # virtual cheaper
    #             "vegasncallsVJVIRT": 10000000,

    #             # -----------------------------------------
    #             # batches
    #             # -----------------------------------------

    #             "cubanbatch": 5000,
    #         })

    # =====================================================
    # ULTRA SUPPRESSED REGION
    #
    # delta >> 0
    #
    # essentially kinematic tail
    #
    # precision completely unnecessary
    #
    # goal:
    #
    # -> finite result
    # -> reasonable shape
    # -> avoid week-long jobs
    # =====================================================

    else:

        params.update({

            # -----------------------------------------
            # FULL VEGAS MODE
            # -----------------------------------------

            "BORNquad": "false",
            "CTquad":   "false",
            "FPCquad":  "false",

            "VJquad":   "false",

            # -----------------------------------------
            # ultra-light setup
            # -----------------------------------------

            "vegasncallsBORN":   1000000,
            "vegasncallsCT":     1000000,

            "vegasncallsVJLO":   2000000,
            "vegasncallsVJREAL": 5000000,
            "vegasncallsVJVIRT": 2000000,

            # -----------------------------------------
            # tiny batches
            # -----------------------------------------

            "cubanbatch": 2000,
        })

        # =================================================
        # N3LL
        # =================================================

        if order_name == "N3LL":

            params.update({

                # -----------------------------------------
                # resummed pieces
                # -----------------------------------------

                "vegasncallsBORN":   2000000,
                "vegasncallsCT":     2000000,

                # -----------------------------------------
                # V+J
                # -----------------------------------------

                "vegasncallsVJLO":   5000000,

                # REAL still dominant
                "vegasncallsVJREAL": 10000000,

                "vegasncallsVJVIRT": 5000000,

                # -----------------------------------------
                # batches
                # -----------------------------------------

                "cubanbatch": 2000,
            })

    return params

# -------------------------
# detect EOS
# -------------------------

cwd = os.getcwd()

on_eos = cwd.startswith("/eos/")

timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

if on_eos:

    afs_base = "/afs/cern.ch/user/a/abulla/private/LOG1/jobs/DYturbo"

    tarball_dest = (
        "/eos/user/a/abulla/CMSSW_14_0_21/src/"
        "dyturbo-1.4.2-empire.tar.gz"
    )

    tarball_source = (
        "/eos/user/a/abulla/CMSSW_14_0_21/src"
    )

else:

    afs_base = "/gwpool/users/abulla/private/jobs/DYturbo"

    tarball_dest = (
        "/gwpool/users/abulla/DYTurbo/"
        "dyturbo-1.4.2-empire.tar.gz"
    )

    tarball_source = (
        "/gwpool/users/abulla/DYTurbo"
    )

# prende il tag dopo DYTurbo-results/
process = "unknown"

if "DYTurbo-results/" in cwd:
    process = cwd.split("DYTurbo-results/")[1].split("/")[0]

workdir = f"{afs_base}/{process}"
os.makedirs(workdir, exist_ok=True)

jobs_dir = f"{workdir}/jobs"
logs_dir = f"{workdir}/logs"

outputs_dir = f"outputs"

# crea cartelle
os.makedirs(jobs_dir, exist_ok=True)
os.makedirs(logs_dir, exist_ok=True)
os.makedirs(outputs_dir, exist_ok=True)

# -------------------------
# tar DYturbo compiled files
# -------------------------

print(f"[INFO] Creating tarball: {tarball_dest}")

# subprocess.run([
#     "tar",
#     "-czf",
#     tarball_dest,
#     "-C",
#     tarball_source,
#     "dyturbo-1.4.2-empire"
# ], check=True)

subprocess.run([
    "cp", "-f", tarball_dest, os.path.dirname(os.path.dirname(jobs_dir))
], check=True)

subprocess.run(["cp", executable, jobs_dir], cwd=os.getcwd(), check=True)

# -------------------------
# loop
# -------------------------

qt_edges  = list(range(0, 102, 2))
ptl_edges = list(range(26, 62, 2))
ptl_edges = [25] + ptl_edges

queue_entries = []

for cfg in configs:

    obs = os.path.basename(cfg).replace(".in", "")

    qt_group_size = 1

    # =================================================
    # qT loop
    # =================================================

    for iqt in range(
        0,
        len(qt_edges)-1,
        qt_group_size
    ):

        sub_qt_edges = qt_edges[
            iqt:iqt+qt_group_size+1
        ]

        qt_bins_string = " ".join(
            map(str, sub_qt_edges)
        )

        qt_low  = sub_qt_edges[0]
        qt_high = sub_qt_edges[-1]

        qt_tag = f"qt{qt_low}_{qt_high}"

        # =============================================
        # empirical critical diagonal
        #
        # pT_critical ~ 45 + 0.6*qT
        #
        # above this:
        # - cancellations explode
        # - quadrature dies
        # - vegas variance explodes
        # =============================================

        pt_critical = 45 + 0.6 * qt_high

        # =============================================
        # high-qT region
        #
        # above ~35 GeV:
        # no pathological phase-space remains
        #
        # merge all pT bins
        # =============================================

        if qt_high >= 35:

            ptl_groups = [ptl_edges]

        # =============================================
        # adaptive low-qT grouping
        # =============================================

        else:

            ptl_groups = []

            ipt = 0

            while ipt < len(ptl_edges)-1:

                ptl_low_tmp = ptl_edges[ipt]

                # -------------------------------------
                # distance from pathological diagonal
                # -------------------------------------

                delta = (
                    ptl_low_tmp - pt_critical
                )

                # -------------------------------------
                # adaptive refinement
                # -------------------------------------

                if delta >= 0:

                    # pathological
                    ptl_group_size = 1

                elif delta >= -5:

                    # very delicate
                    ptl_group_size = 2

                elif delta >= -10:

                    # difficult
                    ptl_group_size = 3

                elif delta >= -15:

                    # moderate
                    ptl_group_size = 5

                elif delta >= -20:

                    # safe
                    ptl_group_size = 8

                else:

                    # very safe
                    ptl_group_size = 12

                # -------------------------------------
                # avoid overflow
                # -------------------------------------

                remaining = (
                    len(ptl_edges)-1 - ipt
                )

                ptl_group_size = min(
                    ptl_group_size,
                    remaining
                )

                # -------------------------------------
                # build pT group
                # -------------------------------------

                sub_ptl_edges = ptl_edges[
                    ipt:ipt+ptl_group_size+1
                ]

                ptl_groups.append(
                    sub_ptl_edges
                )

                ipt += ptl_group_size

        print("")
        print(
            f"[INFO] qT = [{qt_low}, {qt_high}] "
            f"--> generated {len(ptl_groups)} pT groups"
        )

        # =============================================
        # pT loop
        # =============================================

        for sub_ptl_edges in ptl_groups:

            ptl_bins_string = " ".join(
                map(str, sub_ptl_edges)
            )

            ptl_low  = sub_ptl_edges[0]
            ptl_high = sub_ptl_edges[-1]

            ptl_tag = f"ptl{ptl_low}_{ptl_high}"

            # =========================================
            # perturbative orders
            # =========================================

            for order_name, order_value in orders.items():

                if order_value == 3:

                    variations = [
                        (1.0, 1.0, 1.0)
                    ]

                else:

                    variations = scale_variations

                # =====================================
                # adaptive vegas setup
                # =====================================

                vegas_params = get_vegas_params(
                    qt_low,
                    qt_high,
                    ptl_low,
                    ptl_high,
                    order_name
                )

                # =====================================
                # scale variations
                # =====================================

                for muR, muF, muQ in variations:

                    tag = (
                        f"{process}_{obs}_"
                        f"{qt_tag}_"
                        f"{ptl_tag}_"
                        f"{order_name}_"
                        f"muR{muR}_"
                        f"muF{muF}_"
                        f"muQ{muQ}"
                    )

                    cfg_out = (
                        f"{jobs_dir}/{tag}.in"
                    )

                    modify_config(
                        cfg,
                        cfg_out,
                        order_value,
                        muR,
                        muF,
                        muQ,
                        tag,
                        qt_bins_string,
                        ptl_bins_string,
                        vegas_params
                    )

                    queue_entries.append(
                        f"{jobs_dir}/{tag}"
                    )

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
# create submit files split by perturbative order
# =====================================================

submit_files = {}

for order_name in orders.keys():

    submit = f"""
executable = run_dyturbo.sh

arguments = $(cfg).in

output = /dev/null
error  = /dev/null
log    = /dev/null

getenv = True

should_transfer_files = YES

transfer_input_files = run_dyturbo.sh,$(cfg).in,../../{tarball_dest.split('/')[-1]}

+JobFlavour = "tomorrow"

max_materialize = 1000

JobBatchName = "DYTurbo_{process}_{order_name}"

{extra_requirements}

queue cfg in (
"""

    # ---------------------------------------------
    # keep only matching order
    # ---------------------------------------------

    matching = []

    for q in queue_entries:

        if f"_{order_name}_" in q:

            matching.append(q)

    submit += "\n".join(matching)

    submit += "\n)\n"

    # ---------------------------------------------
    # write submit file
    # ---------------------------------------------

    subfile = (
        f"{jobs_dir}/submit_{order_name}.jds"
    )

    with open(subfile, "w") as f:

        f.write(submit)

    submit_files[order_name] = subfile

    print("")
    print(
        f"[INFO] Created submit file: "
        f"{subfile}"
    )

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