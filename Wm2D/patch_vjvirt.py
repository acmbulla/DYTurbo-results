#!/usr/bin/env python3
"""
patch_vjvirt.py

Per ogni file .log in outputs/ (che contiene solo il V+J Virtual
con nstart=20M), trova il corrispondente file in outputs1/ (che contiene
tutti i termini ma con Virtual non converso) e:

1. Sostituisce SOLO il blocco Vegas del V+J Virtual (header + iterazioni
   + riga risultato cella), fermandosi alla riga ┣━━━ che separa il
   blocco dalla summary row -- cosi' la summary row a 5 colonne del
   log completo rimane intatta (tranne Virtual e TOTAL che vengono
   aggiornati)
2. Aggiorna la riga di sommario a 5 colonne con il nuovo valore Virtual
3. Ricalcola il TOTAL come somma dei 4 termini
4. Aggiorna il .txt in outputs1/ con il nuovo totale e errore propagato

outputs/  = Virtual-only logs (nuovo, nstart=20M)
outputs1/ = log completi con tutti i termini (da patchare)

Usage:
    python3 patch_vjvirt.py --outputs outputs --outputs1 outputs1 --dry-run
    python3 patch_vjvirt.py --outputs outputs --outputs1 outputs1 --backup
"""

import os
import re
import math
import argparse
import shutil

# -------------------------------------------------------
# CLI
# -------------------------------------------------------

parser = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--outputs",  default="outputs",  help="dir with Virtual-only logs (nstart=20M)")
parser.add_argument("--outputs1", default="outputs1", help="dir with full logs (all 4 terms, to patch)")
parser.add_argument("--dry-run",  action="store_true", help="print what would be done without writing")
parser.add_argument("--backup",   action="store_true", help="save .bak copy of files before patching")
args = parser.parse_args()

# -------------------------------------------------------
# regex: finalized result cell
# -------------------------------------------------------
RESULT_RE = re.compile(
    r"([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*±\s*(\d+\.?\d*(?:[eE][-+]?\d+)?)"
    r"(?:\s*·10([⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+))?\s*"
    r"\(\s*(\d+\.?\d*)\s*(s|mi|hr)\s*\)"
)

SUPERSCRIPT_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")

def parse_exp(s):
    if not s:
        return None
    return int(s.translate(SUPERSCRIPT_MAP))

def parse_result(text):
    """Return (value, error) from the LAST RESULT_RE match in text."""
    matches = list(RESULT_RE.finditer(text))
    if not matches:
        return None, None
    m = matches[-1]
    val = float(m.group(1))
    err = float(m.group(2))
    exp = parse_exp(m.group(3))
    if exp is not None:
        val *= 10.0 ** exp
        err *= 10.0 ** exp
    return val, err


# -------------------------------------------------------
# Vegas header block regex
# -------------------------------------------------------

VEGAS_HEADER_RE = re.compile(
    r"Vegas input parameters:\s*\n"
    r"(?:.*\n)*?"
    r"\s*statefile\s*.*\n"
)

# -------------------------------------------------------
# find the V+J Virtual Vegas block in a log.
#
# Returns (start, end) where:
#   start = beginning of the Vegas header
#   end   = position of the first ┣ line after the result cell
#           (i.e. the block includes header+iterations+result cell
#            but NOT the ┣ separator or anything after it)
#
# This works for BOTH the Virtual-only log (2-column table) and
# the full log (5-column table) -- in both cases the Virtual block
# ends just before the ┣━━━ separator.
# -------------------------------------------------------

def find_virtual_block(text):
    """Find (start, end) of the V+J Virtual Vegas block.
    end points to the ┣ separator line (not included in block).
    Returns (None, None) if not found.
    """
    headers = list(VEGAS_HEADER_RE.finditer(text))
    if not headers:
        return None, None

    ndim8_headers = [h for h in headers if "ndim 8" in h.group(0)]
    if not ndim8_headers:
        return None, None

    # last ndim=8 header followed by "Iteration 1:"
    virtual_header = None
    for h in reversed(ndim8_headers):
        after = text[h.end():h.end() + 500]
        if "Iteration 1:" in after:
            virtual_header = h
            break

    if virtual_header is None:
        return None, None

    block_start = virtual_header.start()

    # find the ┣ separator that follows the Virtual block
    # search from block_start onwards
    sep_pos = text.find("┣", block_start)
    if sep_pos == -1:
        return None, None

    # block_end = start of the ┣ line
    # (go back to start of that line)
    line_start = text.rfind("\n", block_start, sep_pos)
    if line_start == -1:
        block_end = sep_pos
    else:
        block_end = line_start + 1  # include the \n before ┣

    return block_start, block_end


# -------------------------------------------------------
# extract Virtual block text + value from a Virtual-only log
# -------------------------------------------------------

def extract_virtual_from_virt_log(text):
    """From a Virtual-only log (outputs/), extract:
    - raw text of the Vegas block (up to but not including ┣)
    - final (value, error)
    Returns (block_text, value, error) or (None, None, None).
    """
    start, end = find_virtual_block(text)
    if start is None:
        return None, None, None
    block_text = text[start:end]
    val, err = parse_result(block_text)
    return block_text, val, err


# -------------------------------------------------------
# extract 5 summary values from full log
# -------------------------------------------------------

def extract_summary_values(text):
    """Find the summary table row with exactly 5 RESULT_RE matches.
    Returns list of (value, error) in order, or [] if not found."""
    for line in text.split("\n"):
        if not line.startswith("┃"):
            continue
        matches = list(RESULT_RE.finditer(line))
        if len(matches) == 5:
            results = []
            for m in matches:
                val = float(m.group(1))
                err = float(m.group(2))
                exp = parse_exp(m.group(3))
                if exp is not None:
                    val *= 10.0 ** exp
                    err *= 10.0 ** exp
                results.append((val, err))
            return results
    return []


# -------------------------------------------------------
# update the 5-column summary row with new Virtual + TOTAL
# -------------------------------------------------------

def format_cell(val, err, old_match):
    """Format a (val, err) pair to match the style of old_match.

    If old_match had a shared exponent (·10⁺⁰³ etc.), apply the same
    exponent and format accordingly. The time string is kept from the
    original cell. The formatted string is padded to match the original
    cell width so the ┃ column borders stay aligned.
    """
    old_text  = old_match.group(0)
    time_str  = f"{old_match.group(4)}{old_match.group(5)}"
    exp       = parse_exp(old_match.group(3))
    sup       = old_match.group(3)  # unicode superscript string or None

    if exp is not None:
        v = val / (10.0 ** exp)
        e = err / (10.0 ** exp)
        new_text = f"{v:.5g} ± {e:.5g} ·10{sup} ({time_str})"
    else:
        v = val
        e = err
        new_text = f"{v:.5g} ± {e:.5g}        ({time_str})"

    # pad to same length as original so column widths are preserved
    old_len = len(old_text)
    new_len = len(new_text)
    if new_len < old_len:
        # pad before the opening parenthesis of the time
        paren = new_text.rfind("(")
        new_text = new_text[:paren] + " " * (old_len - new_len) + new_text[paren:]
    # if new_text is longer, leave it (table may stretch slightly)

    return new_text


def update_summary_row(text, new_virt_val, new_virt_err,
                       new_total_val, new_total_err):
    """Replace columns 4 (Virtual) and 5 (TOTAL) in the 5-column
    summary row, keeping Resum/CT/Real unchanged."""

    lines = text.split("\n")
    new_lines = []
    for line in lines:
        if line.startswith("┃"):
            matches = list(RESULT_RE.finditer(line))
            if len(matches) == 5:
                m4 = matches[3]
                m5 = matches[4]

                new4 = format_cell(new_virt_val,  new_virt_err,  m4)
                new5 = format_cell(new_total_val, new_total_err, m5)

                # replace right to left to preserve positions
                line = line[:m5.start()] + new5 + line[m5.end():]
                line = line[:m4.start()] + new4 + line[m4.start() + (m4.end() - m4.start()):]

        new_lines.append(line)
    return "\n".join(new_lines)


# -------------------------------------------------------
# main patching logic
# -------------------------------------------------------

def patch_file(virt_log, full_log, dry_run=False, backup=False):
    """Replace V+J Virtual in full_log with the one from virt_log,
    update summary row, recompute TOTAL, update .txt."""

    basename = os.path.basename(full_log)
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Processing: {basename}")

    with open(virt_log) as f:
        virt_text = f.read()
    with open(full_log) as f:
        full_text = f.read()

    # --- extract new Virtual block from outputs/ ---
    new_virt_block, new_virt_val, new_virt_err = extract_virtual_from_virt_log(virt_text)
    if new_virt_block is None:
        print(f"  [WARN] could not find Virtual block in {virt_log}, skipping")
        return False
    print(f"  New Virtual: {new_virt_val:.6g} ± {new_virt_err:.6g}")

    # --- extract 5 summary values from full log ---
    summary_vals = extract_summary_values(full_text)
    if len(summary_vals) != 5:
        print(f"  [WARN] expected 5 summary values in {full_log}, "
              f"found {len(summary_vals)}, skipping")
        return False

    resum_val,    resum_err    = summary_vals[0]
    ct_val,       ct_err       = summary_vals[1]
    real_val,     real_err     = summary_vals[2]
    old_virt_val, old_virt_err = summary_vals[3]  # Virtual is column 4
    # summary_vals[4] = old TOTAL (discarded)

    print(f"  Old Virtual: {old_virt_val:.6g} ± {old_virt_err:.6g}")

    # --- find Virtual block boundaries in full log ---
    vstart, vend = find_virtual_block(full_text)
    if vstart is None:
        print(f"  [WARN] could not find Virtual block in {full_log}, skipping")
        return False

    # --- read high-precision total from .txt ---
    full_txt = full_log.replace(".log", ".txt")
    if not os.path.exists(full_txt):
        print(f"  [WARN] .txt not found: {full_txt}, skipping")
        return False

    txt_total_val = None
    txt_total_err = None
    with open(full_txt) as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                parts = stripped.split()
                if len(parts) >= 2:
                    txt_total_val = float(parts[0])
                    txt_total_err = float(parts[1])
                    break

    if txt_total_val is None:
        print(f"  [WARN] could not read total from {full_txt}, skipping")
        return False

    print(f"  Old TOTAL (txt): {txt_total_val:.15g} ± {txt_total_err:.15g}")

    # --- compute new TOTAL at full precision ---
    # new_total = old_total - old_virt + new_virt
    # new_err   = sqrt(old_err^2 - old_virt_err^2 + new_virt_err^2)
    new_total_val = txt_total_val - old_virt_val + new_virt_val
    new_total_err = math.sqrt(
        max(0.0, txt_total_err**2 - old_virt_err**2 + new_virt_err**2)
    )

    print(f"  New TOTAL:       {new_total_val:.15g} ± {new_total_err:.15g}")

    if dry_run:
        return True

    # --- backup ---
    if backup:
        shutil.copy2(full_log, full_log + ".bak")
        if os.path.exists(full_txt):
            shutil.copy2(full_txt, full_txt + ".bak")

    # --- patch the log ---
    patched_text = full_text[:vstart] + new_virt_block + full_text[vend:]

    # --- update 5-column summary row ---
    patched_text = update_summary_row(
        patched_text,
        new_virt_val, new_virt_err,
        new_total_val, new_total_err
    )

    # --- update "Total cross section" footer line ---
    patched_text = re.sub(
        r"(Total cross section\s+)([-+]?\d[\d\.\s±eE+\-·⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+)(fb|pb)",
        lambda m: (
            f"{m.group(1)}"
            f"{new_total_val:>12.6g} ± {new_total_err:<10.6g}"
            f"{m.group(3)}"
        ),
        patched_text
    )

    with open(full_log, "w") as f:
        f.write(patched_text)
    print(f"  Patched log: {full_log}")

    # --- update .txt with full precision ---
    with open(full_txt) as f:
        txt_lines = f.readlines()

    new_txt_lines = []
    for line in txt_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            new_txt_lines.append(f"{new_total_val} {new_total_err}\n")
        else:
            new_txt_lines.append(line)

    with open(full_txt, "w") as f:
        f.writelines(new_txt_lines)
    print(f"  Patched txt: {full_txt}")

    return True


# -------------------------------------------------------
# main
# -------------------------------------------------------

outputs_dir  = args.outputs
outputs1_dir = args.outputs1

virt_logs = sorted(
    f for f in os.listdir(outputs_dir)
    if f.endswith(".log")
)

n_ok   = 0
n_fail = 0
n_skip = 0

for fname in virt_logs:
    virt_log = os.path.join(outputs_dir,  fname)
    full_log = os.path.join(outputs1_dir, fname)

    if not os.path.exists(full_log):
        print(f"\n[SKIP] no matching full log for {fname}")
        n_skip += 1
        continue

    ok = patch_file(virt_log, full_log, dry_run=args.dry_run, backup=args.backup)
    if ok:
        n_ok += 1
    else:
        n_fail += 1

print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}Done: "
      f"{n_ok} patched, {n_fail} failed, {n_skip} skipped")