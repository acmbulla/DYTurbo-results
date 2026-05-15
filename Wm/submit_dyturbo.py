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
    qt_bins_string
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

        else:
            new_lines.append(line)

    with open(output, "w") as f:
        f.writelines(new_lines)


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

qt_edges = list(range(0, 102, 2))

queue_entries = []

for cfg in configs:

    obs = os.path.basename(cfg).replace(".in", "")

    qt_group_size = 1

    for i in range(0, len(qt_edges)-1, qt_group_size):

        sub_edges = qt_edges[i:i+qt_group_size+1]

        qt_bins_string = " ".join(map(str, sub_edges))

        qt_low  = sub_edges[0]
        qt_high = sub_edges[-1]

        qt_tag = f"qt{qt_low}_{qt_high}"

        for order_name, order_value in orders.items():

            if order_value == 3:
                variations = [(1.0, 1.0, 1.0)]
            else:
                variations = scale_variations

            for muR, muF, muQ in variations:

                tag = (
                    f"{process}_{obs}_{qt_tag}_"
                    f"{order_name}_"
                    f"muR{muR}_muF{muF}_muQ{muQ}"
                )

                cfg_out = f"{jobs_dir}/{tag}.in"

                modify_config(
                    cfg,
                    cfg_out,
                    order_value,
                    muR,
                    muF,
                    muQ,
                    tag,
                    qt_bins_string
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

# -------------------------
# create unique submit file
# -------------------------

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

{extra_requirements}

queue cfg in (
"""

submit += "\n".join(queue_entries)

submit += "\n)\n"

# -------------------------
# write submit file
# -------------------------

master_subfile = f"{jobs_dir}/submit_all.jds"

with open(master_subfile, "w") as f:
    f.write(submit)

print(f"[INFO] Created submit file: {master_subfile}")

# -------------------------
# submit
# -------------------------

# submit_dir = os.path.dirname(master_subfile)

# subprocess.run(
#     ["condor_submit", os.path.basename(master_subfile)],
#     cwd=submit_dir,
#     check=True
# )

# print("[INFO] Submitted all jobs")