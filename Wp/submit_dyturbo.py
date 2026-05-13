#!/usr/bin/env python3

import os
import itertools
import subprocess

# -------------------------
# user config
# -------------------------

configs = [
    "Template/qt.in",
    "Template/ptl.in",
    "Template/etal.in",
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
    (0.5, 0.5),
    (2.0, 2.0),
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
    tag
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

        else:
            new_lines.append(line)

    with open(output, "w") as f:
        f.writelines(new_lines)


# -------------------------
# loop
# -------------------------

for cfg in configs:

    obs = os.path.basename(cfg).replace(".in", "")

    for order_name, order_value in orders.items():

        if order_value == 3:
            variations = [(1.0, 1.0)]
        else:
            variations = scale_variations

        for muR, muF in variations:

            tag = f"{obs}_{order_name}_muR{muR}_muF{muF}"

            cfg_out = f"jobs/{tag}.in"

            modify_config(
                cfg,
                cfg_out,
                order_value,
                muR,
                muF,
                tag
            )

            submit = f'''
executable = run_dyturbo.sh

arguments = {cfg_out}

output = logs/{tag}.out
error  = logs/{tag}.err
log    = logs/{tag}.log

getenv = True

+JobFlavour = "tomorrow"

request_cpus = 1
request_memory = 2048
Requirements = (machine == "hercules02.hcms.it")

queue
'''

            subfile = f"jobs/{tag}.sub"

            with open(subfile, "w") as f:
                f.write(submit)

            subprocess.run(
                ["condor_submit", subfile]
            )

            print(f"[SUBMITTED] {tag}")