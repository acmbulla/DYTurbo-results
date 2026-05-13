#!/usr/bin/env python3

import os
import itertools
import subprocess

# -------------------------
# user config
# -------------------------

configs = [
    "Template/qt.in",
]

orders = {
    "NLL": 1,
    "NNLL": 2,
    "N3LL": 3,
}

scale_variations = [
    (1.0, 1.0),
    (2.0, 1.0),
    (0.5, 1.0),
    (1.0, 2.0),
    (1.0, 0.5),
    (2.0, 2.0),
    (0.5, 0.5),
]

dyturbo_bin = "./bin/dyturbo"

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
# loop
# -------------------------

qt_edges = list(range(0, 102, 2))

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
                variations = [(1.0, 1.0)]
            else:
                variations = scale_variations

            for muR, muF in variations:

                tag = (
                    f"{obs}_{qt_tag}_"
                    f"{order_name}_"
                    f"muR{muR}_muF{muF}"
                )

                cfg_out = f"jobs/{tag}.in"

                modify_config(
                    cfg,
                    cfg_out,
                    order_value,
                    muR,
                    muF,
                    tag,
                    qt_bins_string
                )

                submit = f'''
executable = run_dyturbo.sh

arguments = {cfg_out}

output = logs/{tag}.out
error  = logs/{tag}.err
log    = logs/{tag}.log

+JobFlavour = "tomorrow"

request_cpus = 1
request_memory = 1024

queue
'''

                subfile = f"jobs/{tag}.sub"

                with open(subfile, "w") as f:
                    f.write(submit)

                subprocess.run(
                    ["condor_submit", subfile]
                )

                print(f"[SUBMITTED] {tag}")