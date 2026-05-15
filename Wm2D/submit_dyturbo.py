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
    "NNLL": 2,
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

        elif stripped.startswith("vegasncalls"):
            new_lines.append(
                f"vegasncalls = {vegas_params['vegasncalls']}\n"
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
        # vegas controls
        # ---------------------------------------------

        "vegasncalls": 20_000_000,

        # IMPORTANT:
        # large batch stabilizes importance map
        "cubanbatch": 10_000,
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

            "vegasncalls": 20_000_000,

            "cubanbatch": 10_000,
        })

        # ---------------------------------------------
        # N3LL needs more stability
        # ---------------------------------------------

        if order_name == "N3LL":

            params.update({

                "vegasncalls": 100_000_000,

                "cubanbatch": 50_000,
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

            # more statistics
            "vegasncalls": 150_000_000,

            # MUCH more stable grid adaptation
            "cubanbatch": 100_000,
        })

        if order_name == "N3LL":

            params.update({

                "vegasncalls": 300_000_000,

                "cubanbatch": 100_000,
            })

    # =====================================================
    # PATHOLOGICAL REGION
    #
    # qT very small + pT too high
    #
    # observations from logs:
    #
    # - quadrature explodes to O(100h)
    # - vegas converges in minutes-hours
    #
    # therefore:
    #
    # -> switch EVERYTHING to vegas
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
            # robust vegas setup
            # -----------------------------------------

            # allow long convergence
            # but avoid quadrature death
            "vegasncalls": 300_000_000,

            # HUGE batches stabilize the grid
            "cubanbatch": 100_000,
        })

        if order_name == "N3LL":

            params.update({

                "vegasncalls": 500_000_000,

                "cubanbatch": 200_000,
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

# -------------------------
# loop
# -------------------------

qt_edges  = list(range(0, 102, 2))
ptl_edges = list(range(25, 61, 1))

queue_entries = []

for cfg in configs:

    obs = os.path.basename(cfg).replace(".in", "")

    qt_group_size = 1

    # =================================================
    # qT loop
    # =================================================

    for iqt in range(0, len(qt_edges)-1, qt_group_size):

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
        # adaptive pT splitting
        # =============================================

        if qt_high <= 10:
            ptl_group_size = 1

        elif qt_high <= 20:
            ptl_group_size = 2

        elif qt_high <= 50:
            ptl_group_size = 5

        else:
            ptl_group_size = len(ptl_edges)

        print("")
        print(
            f"[INFO] qT = [{qt_low}, {qt_high}] "
            f"--> ptl_group_size = {ptl_group_size}"
        )

        # =============================================
        # pT loop
        # =============================================

        for ipt in range(
            0,
            len(ptl_edges)-1,
            ptl_group_size
        ):

            sub_ptl_edges = ptl_edges[
                ipt:ipt+ptl_group_size+1
            ]

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

                # =================================
                # adaptive vegas setup
                # =================================

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
# =====================================================
# create submit files split by perturbative order
# =====================================================

submit_files = {}

for order_name in orders.keys():

    submit = f"""
executable = run_dyturbo.sh

arguments = $(cfg).in

output = $(cfg).out
error  = $(cfg).err
log    = $(cfg).log

getenv = True

should_transfer_files = YES

transfer_input_files = run_dyturbo.sh,$(cfg).in,../../{tarball_dest.split('/')[-1]}

+JobFlavour = "tomorrow"

max_materialize = 500

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

# =====================================================
# submit all
# =====================================================

for order_name, subfile in submit_files.items():

    print("")
    print(
        f"[INFO] Submitting {order_name}"
    )

    subprocess.run(
        [
            "condor_submit",
            os.path.basename(subfile)
        ],
        cwd=os.path.dirname(subfile),
        check=True
    )

print("")
print("[INFO] Submitted all jobs")