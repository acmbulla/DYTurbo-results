#!/usr/bin/env python3
"""
patch_terms.py

Unica directory che contiene sia i log parziali (un termine per file:
BORN, CT, VJREAL, VJVIRT) sia i log completi (tutti i termini) sia
i file di output.

CASO A — il log completo esiste già nella stessa directory:
    Sostituisce il blocco Vegas del termine nel log completo e ricalcola
    il TOTAL. Sovrascrive il log completo originale.
    Aggiorna anche il .txt corrispondente.

CASO B — il log completo NON esiste (solo per NNLL/N3LL):
    Assembla un log sintetico da tutti i pezzi parziali disponibili
    (BORN + CT + VJREAL + VJVIRT). Se mancano pezzi, emette un warning
    BEN VISIBILE ma assembla comunque con i pezzi disponibili.
    Scrive <nome>.log e <nome>.txt nella stessa directory.

NLL: ha sempre un log completo → solo Caso A. Se non c'è il log
     completo per un gruppo NLL, warning + skip (il VJ non esiste come
     pezzo standalone per NLL).

Naming convention attesa per i log parziali:
    <process>_<obs>_qt<qtlo>_<qthi>_ptl<ptlo>_<pthi>_<ORDER>_<TERM>_muR<r>_muF<f>_muQ<q>.log
    TERM ∈ {BORN, CT, VJREAL, VJVIRT}

Naming convention del log completo corrispondente:
    <process>_<obs>_qt<qtlo>_<qthi>_ptl<ptlo>_<pthi>_<ORDER>_muR<r>_muF<f>_muQ<q>.log
    (identico ma senza _<TERM>)

Usage:
    python3 patch_terms.py outputs/
    python3 patch_terms.py outputs/ --dry-run
    python3 patch_terms.py outputs/ --backup
"""

import os
import re
import math
import argparse
import shutil
from collections import defaultdict

# -------------------------------------------------------
# CLI
# -------------------------------------------------------

parser = argparse.ArgumentParser(
    description=__doc__,
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
parser.add_argument("directory",
                    help="directory che contiene log parziali, log completi e dove "
                         "verranno scritti i file di output")
parser.add_argument("--dry-run",  action="store_true",
                    help="mostra cosa farebbe senza scrivere nulla")
parser.add_argument("--backup",   action="store_true",
                    help="salva copia .bak prima di sovrascrivere (solo Caso A)")
args = parser.parse_args()

# -------------------------------------------------------
# costanti
# -------------------------------------------------------

ALL_TERMS_NNLL = ["BORN", "CT", "VJREAL", "VJVIRT"]
ALL_TERMS_NLL  = ["BORN", "CT"]          # VJ non è mai standalone per NLL

# colonne attese nel log completo per ordine
FULL_COLUMNS = {
    "NLL":  ["Resummation", "Counter term", "V+J", "TOTAL"],
    "NNLL": ["Resummation", "Counter term", "V+J Real", "V+J Virtual", "TOTAL"],
    "N3LL": ["Resummation", "Counter term", "V+J Real", "V+J Virtual", "TOTAL"],
}

# mappa TERM → colonna nella tabella completa (per il replace del blocco)
TERM_TO_COLUMN = {
    "BORN":   "Resummation",
    "CT":     "Counter term",
    "VJREAL": "V+J Real",
    "VJVIRT": "V+J Virtual",
}

# mappa TERM → header Vegas atteso (ndim) per identificare il blocco
# Resummation: ndim 6, CT: ndim 8 (flags 10), VJReal: ndim 10, VJVirt: ndim 8
TERM_NDIM = {
    "BORN":   6,
    "CT":     8,
    "VJREAL": 10,
    "VJVIRT": 8,
}

# -------------------------------------------------------
# regex
# -------------------------------------------------------

RESULT_RE = re.compile(
    r"([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*±\s*(\d+\.?\d*(?:[eE][-+]?\d+)?)"
    r"(?:\s*·10([⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+))?\s*"
    r"\(\s*(\d+\.?\d*)\s*(s|mi|hr)\s*\)"
)

SUPERSCRIPT_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")

# filename parziale:  ..._<ORDER>_<TERM>_muR..._muF..._muQ...
PARTIAL_FNAME_RE = re.compile(
    r"^(?P<prefix>.+)_"
    r"(?P<order>LO|[A-Za-z0-9]+LL)_"
    r"(?P<term>BORN|CT|VJREAL|VJVIRT)_"
    r"muR(?P<muR>[\d\.]+)_muF(?P<muF>[\d\.]+)_muQ(?P<muQ>[\d\.]+)"
    r"(?P<suffix>\.log)?$"
)

VEGAS_HEADER_RE = re.compile(
    r"Vegas input parameters:\s*\n(?:.*\n)*?(?=Iteration 1:)"
)

# -------------------------------------------------------
# helpers generici
# -------------------------------------------------------

def parse_exp(s):
    if not s:
        return None
    return int(s.translate(SUPERSCRIPT_MAP))


def parse_result_last(text):
    """(value, error) dall'ULTIMO match RESULT_RE nel testo."""
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


def fmt_val_err(val, err, width=8, time_str="0s"):
    """
    Formatta 'val ± err (time)' compatibile con RESULT_RE del parser.
    Usa notazione ·10^N (superscript Unicode) per valori molto grandi/piccoli,
    evitando la notazione Python e+N che RESULT_RE non riconosce.
    time_str: stringa tempo da appendere (default "0s" per le celle assembled).
    """
    if val == 0 and err == 0:
        return f"{'0':>{width}} ± {'0':>{width}}        ({time_str})"
    mag = max(abs(val), abs(err))
    if mag != 0 and (mag >= 1e4 or mag < 0.01):
        exp = int(math.floor(math.log10(mag) / 3) * 3)  # multiplo di 3
        sup = _to_superscript(f"{exp:+03d}")
        v = val / 10 ** exp
        e = err / 10 ** exp
        return f"{v:>{width}.4g} ± {e:>{width}.4g} ·10{sup} ({time_str})"
    else:
        return f"{val:>{width}.4g} ± {err:>{width}.4g}        ({time_str})"


def _to_superscript(s):
    normal = "0123456789+-"
    sup    = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻"
    # build map
    m = str.maketrans(normal, sup + "")
    # manual map since translate needs equal length strings
    result = ""
    sup_map = dict(zip("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻"))
    for c in s:
        result += sup_map.get(c, c)
    return result


def format_cell(val, err, old_match):
    """Riformatta (val,err) cercando di preservare larghezza e stile del match originale."""
    old_text = old_match.group(0)
    time_str = f"{old_match.group(4)}{old_match.group(5)}"
    exp      = parse_exp(old_match.group(3))
    sup      = old_match.group(3)

    if exp is not None:
        v = val / (10.0 ** exp)
        e = err / (10.0 ** exp)
        new_text = f"{v:.5g} ± {e:.5g} ·10{sup} ({time_str})"
    else:
        new_text = f"{val:.5g} ± {err:.5g}        ({time_str})"

    old_len = len(old_text)
    new_len = len(new_text)
    if new_len < old_len:
        paren = new_text.rfind("(")
        new_text = new_text[:paren] + " " * (old_len - new_len) + new_text[paren:]
    return new_text


# -------------------------------------------------------
# parsing filename parziale
# -------------------------------------------------------

def parse_partial_filename(fname):
    """
    Ritorna dict con prefix, order, term, muR, muF, muQ
    o None se il filename non corrisponde.
    """
    base = os.path.basename(fname)
    if base.endswith(".log"):
        base = base[:-4]
    m = PARTIAL_FNAME_RE.match(base)
    if not m:
        return None
    return {
        "prefix": m.group("prefix"),
        "order":  m.group("order"),
        "term":   m.group("term"),
        "muR":    float(m.group("muR")),
        "muF":    float(m.group("muF")),
        "muQ":    float(m.group("muQ")),
        "muR_str": m.group("muR"),
        "muF_str": m.group("muF"),
        "muQ_str": m.group("muQ"),
    }


def _scale_variants(v):
    """Possibili rappresentazioni stringa di una scala nei filename."""
    return {f"{v:g}", f"{v:.1f}", f"{v:.2f}"}


def _find_full_file(directory, prefix, order, muR, muF, muQ, ext):
    """
    Cerca il file completo (senza _TERM_) provando tutte le varianti di
    rappresentazione delle scale (muR1 vs muR1.0 vs muR1.00 ecc.).
    Ritorna il path se trovato, None altrimenti.
    """
    import glob as _glob
    for r in _scale_variants(muR):
        for f_ in _scale_variants(muF):
            for q in _scale_variants(muQ):
                pattern = os.path.join(
                    directory,
                    f"{prefix}_{order}_muR{r}_muF{f_}_muQ{q}{ext}"
                )
                matches = _glob.glob(pattern)
                # escludi i _patched già prodotti
                matches = [m for m in matches
                           if "_patched" not in os.path.basename(m)]
                if matches:
                    return matches[0]
    return None


def full_log_name(prefix, order, muR, muF, muQ):
    """Nome canonico del log originale completo (usato per cercarlo su disco)."""
    return f"{prefix}_{order}_muR{muR:g}_muF{muF:g}_muQ{muQ:g}.log"


def assembled_log_name(prefix, order, muR, muF, muQ, muR_str, muF_str, muQ_str):
    """Nome del log sintetico assemblato (uguale al nome del log completo originale)."""
    return f"{prefix}_{order}_muR{muR_str}_muF{muF_str}_muQ{muQ_str}.log"


def full_txt_name(prefix, order, muR, muF, muQ):
    return f"{prefix}_{order}_muR{muR:g}_muF{muF:g}_muQ{muQ:g}.txt"


def assembled_txt_name(prefix, order, muR, muF, muQ, muR_str, muF_str, muQ_str):
    return f"{prefix}_{order}_muR{muR_str}_muF{muF_str}_muQ{muQ_str}.txt"


# -------------------------------------------------------
# estrazione blocco Vegas da un log parziale
# -------------------------------------------------------

def find_vegas_block(text, term):
    """
    Trova (start, end) del blocco Vegas per il termine dato nel testo.

    Nel log COMPLETO i blocchi Vegas sono separati dal carattere ┃ sulla
    stessa riga (non da newline). La struttura è:
        ┃<blocco0>val±err(time) ┃<blocco1>val±err(time) ┃...┃TOTAL┃

    Ogni blocco inizia DOPO un ┃ che precede "Vegas input parameters:".
    Il blocco termina al ┃ successivo (inizio del prossimo blocco) o al ┣/┗.

    Ordine dei blocchi:
        NNLL: [0]=BORN(ndim6) [1]=CT(ndim8) [2]=VJREAL(ndim10) [3]=VJVIRT(ndim8)
        NLL:  [0]=BORN(ndim6) [1]=CT(ndim8) [2]=V+J(ndim7)

    Nei log PARZIALI c'è un solo blocco → il primo con "Iteration 1:".

    Ritorna (block_start, block_end):
        block_start: posizione del 'V' di "Vegas..." (┃ precedente NON incluso)
        block_end:   posizione del ┃ che inizia la cella successiva,
                     o inizio della riga ┣/┗ se ultima cella
    """
    ndim = TERM_NDIM[term]

    # Raccoglie l'inizio di ogni cella Vegas nel testo.
    # In un log completo ogni cella inizia con "┃Vegas..." (il ┃ è il
    # separatore di colonna della tabella box-drawing di DYTurbo).
    # In un log parziale il primo blocco può iniziare senza ┃.
    cell_starts = []
    for m in re.finditer(r"┃Vegas input parameters:", text):
        cell_starts.append(m.start() + 1)  # posizione dopo ┃
    # Vegas senza ┃ immediato (log parziale o inizio tabella)
    for m in re.finditer(r"Vegas input parameters:", text):
        pos = m.start()
        if pos == 0 or text[pos - 1] != "┃":
            cell_starts.append(pos)

    cell_starts = sorted(set(cell_starts))
    if not cell_starts:
        return None, None

    # Per ogni cella determina ndim e presenza di Iteration 1.
    # La fine di ogni cella è l'inizio della cella successiva - 1 (il ┃),
    # oppure l'inizio della riga ┣/┗.
    cells = []
    for i, cs in enumerate(cell_starts):
        # fine provvisoria: inizio della prossima cella (il ┃ che la precede)
        if i + 1 < len(cell_starts):
            ce = cell_starts[i + 1] - 1  # il ┃ separatore NON è nel blocco
        else:
            ce = len(text)

        # ma ┣/┗ termina sempre la cella corrente
        sep_m = re.search(r"[┣┗]", text[cs:ce])
        if sep_m:
            sep_abs = cs + sep_m.start()
            line_s = text.rfind("\n", cs, sep_abs)
            ce = (line_s + 1) if line_s != -1 else sep_abs

        cell_text = text[cs:ce]
        ndim_m = re.search(r"ndim\s+(\d+)", cell_text)
        ndim_found = int(ndim_m.group(1)) if ndim_m else -1
        has_iter = "Iteration 1:" in cell_text
        cells.append((cs, ce, ndim_found, has_iter))

    # filtra per ndim corretto e con Iteration 1
    matching = [(cs, ce) for cs, ce, nd, hi in cells if nd == ndim and hi]

    if not matching:
        return None, None

    # CT = 1° blocco ndim=8, VJVIRT = 2° blocco ndim=8
    if term == "VJVIRT" and len(matching) >= 2:
        return matching[1]
    return matching[0]

def extract_partial_block(path, term):
    """
    Da un log parziale estrae il blocco Vegas (header + iterazioni + riga risultato)
    e il risultato finale del termine.
    Ritorna (block_text, value, error) oppure (None, None, None) su errore.
    """
    with open(path, "r", errors="replace") as f:
        text = f.read()

    start, end = find_vegas_block(text, term)

    # --- caso Gauss/cuhre: nessun blocco Vegas ---
    if start is None:
        # leggi valore dalla PRIMA riga ┃ con RESULT_RE match dopo QUALSIASI ┣
        # (funziona sia per Gauss puro che per cuhre)
        # Usiamo parse_result_last sull'intera tabella per semplicità:
        # estraiamo il testo dalla prima ┣ alla fine e prendiamo il primo match
        table_start = text.find("┣")
        if table_start != -1:
            table_text = text[table_start:]
            for line in table_text.split("\n"):
                if not line.startswith("┃"):
                    continue
                m = RESULT_RE.search(line)
                if m:
                    val = float(m.group(1))
                    err = float(m.group(2))
                    exp = parse_exp(m.group(3))
                    if exp is not None:
                        val *= 10.0 ** exp
                        err *= 10.0 ** exp
                    return None, val, err
        return None, None, None

    # --- caso Vegas ---
    block_text = text[start:end]
    val, err = parse_result_last(block_text)
    if val is None:
        return None, None, None

    # i log parziali hanno la tabella a 2+ colonne: la riga finale è
    # "  val ± err (time) ┃  val_TOTAL ± err_TOTAL (time) ┃"
    # Il primo risultato è il valore della cella, il secondo è il TOTAL
    # ridondante del log parziale. Tronchiamo al ┃ che separa i due,
    # così nel log completo il ┃ viene aggiunto esternamente una sola volta.
    # trova l'ultima riga che contiene un RESULT_RE match
    # (non necessariamente l'ultima riga del blocco -- può esserci una "┃" orfana dopo)
    lines = block_text.split("\n")
    for i in range(len(lines) - 1, -1, -1):
        first_match = RESULT_RE.search(lines[i])
        if first_match:
            # tronca alla fine del primo risultato su quella riga
            # (il testo dopo è il TOTAL ridondante del log parziale)
            prefix = "\n".join(lines[:i]) + ("\n" if i > 0 else "")
            block_text = (prefix + lines[i][:first_match.end()]).rstrip()
            break

    return block_text, val, err


# -------------------------------------------------------
# CASO A — patch di un termine nel log completo
# -------------------------------------------------------

def extract_full_summary(text):
    """
    Estrae i valori della summary row a N colonne dal log completo.
    Ritorna lista di (value, error) in ordine di colonna, o [] se non trovata.
    Usa la riga ┃ con il massimo numero di match RESULT_RE.
    """
    best = []
    for line in text.split("\n"):
        if not line.startswith("┃"):
            continue
        matches = list(RESULT_RE.finditer(line))
        if len(matches) > len(best):
            results = []
            for m in matches:
                val = float(m.group(1))
                err = float(m.group(2))
                exp = parse_exp(m.group(3))
                if exp is not None:
                    val *= 10.0 ** exp
                    err *= 10.0 ** exp
                results.append((val, err))
            best = results
    return best


def column_index_for_term(term, order):
    """Indice (0-based) del termine nella lista di colonne del log completo."""
    cols = FULL_COLUMNS.get(order, FULL_COLUMNS["NNLL"])
    # rimuovi TOTAL dall'indice (non è un termine calcolabile)
    col_name = TERM_TO_COLUMN[term]
    try:
        return [c for c in cols if c != "TOTAL"].index(col_name)
    except ValueError:
        return None


def update_summary_row_full(text, col_idx, n_data_cols,
                             new_val, new_err,
                             new_total_val, new_total_err):
    """
    Aggiorna la summary row del log completo:
      - colonna col_idx (0-based tra i termini dati, escluso TOTAL)
        con new_val/new_err
      - ultima colonna (TOTAL) con new_total_val/new_total_err
    n_data_cols = numero colonne dati (escluso TOTAL), es. 4 per NNLL.
    """
    lines = text.split("\n")
    new_lines = []
    for line in lines:
        if line.startswith("┃"):
            matches = list(RESULT_RE.finditer(line))
            # la summary row ha n_data_cols + 1 match (incluso TOTAL)
            if len(matches) == n_data_cols + 1:
                m_term  = matches[col_idx]
                m_total = matches[-1]
                new_term  = format_cell(new_val,       new_err,       m_term)
                new_total = format_cell(new_total_val, new_total_err, m_total)
                # sostituisce da destra per preservare le posizioni
                line = line[:m_total.start()] + new_total + line[m_total.end():]
                line = line[:m_term.start()]  + new_term  + line[m_term.start() + len(m_term.group(0)):]
        new_lines.append(line)
    return "\n".join(new_lines)


def patch_terms_in_full_log(partial_logs, full_path, out_path, txt_path,
                             order, dry_run=False, backup=False):
    """
    CASO A: sostituisce tutti i termini di partial_logs nel log completo
    in un unico passaggio, ricalcola il TOTAL una sola volta alla fine.
    partial_logs = { term: partial_path }
    """
    terms = sorted(partial_logs.keys())
    dry = '[DRY-RUN] ' if dry_run else ''
    print(f"\n{dry}[CASO A] patch {terms} in log completo")
    print(f"  full    : {full_path}")
    print(f"  output  : {out_path}")

    with open(full_path, "r", errors="replace") as f:
        full_text = f.read()

    cols = FULL_COLUMNS.get(order, FULL_COLUMNS["NNLL"])
    n_data_cols = len(cols) - 1

    summary = extract_full_summary(full_text)
    if len(summary) != n_data_cols + 1:
        print(f"  [WARN] summary row ha {len(summary)} valori, attesi {n_data_cols + 1}, skip")
        return False

    # leggi total ad alta precisione dal .txt esistente (se c'è)
    old_total_val, old_total_err = summary[-1]
    txt_loaded = False
    if txt_path and os.path.exists(txt_path):
        with open(txt_path) as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#"):
                    parts = s.split()
                    if len(parts) >= 2:
                        try:
                            old_total_val = float(parts[0])
                            old_total_err = float(parts[1])
                            txt_loaded = True
                            break
                        except ValueError:
                            continue

    # estrai blocchi e nuovi valori per tutti i termini
    new_blocks = {}   # term -> block_text
    new_values = {}   # term -> (val, err)
    old_values = {}   # term -> (val, err) dal summary corrente

    for term in terms:
        col_idx = column_index_for_term(term, order)
        if col_idx is None:
            print(f"  [WARN] termine '{term}' non trovato nelle colonne di {order}, skip gruppo")
            return False
        old_values[term] = summary[col_idx]

        partial_path = partial_logs[term]
        block, val, err = extract_partial_block(partial_path, term)
        if val is None:
            # errore reale (né Vegas né Gauss ha prodotto un risultato)
            print(f"  [WARN] impossibile estrarre il risultato '{term}' da {partial_path}, skip gruppo")
            return False
        # block=None è legittimo per quadratura Gauss (nessun blocco Vegas da sostituire)
        new_blocks[term] = block
        new_values[term] = (val, err)

    # stampa riepilogo compatto
    for term in terms:
        ov, oe = old_values[term]
        nv, ne = new_values[term]
        col_name = TERM_TO_COLUMN[term]
        print(f"  {col_name:20s}: {ov:.6g} ± {oe:.6g}  →  {nv:.6g} ± {ne:.6g}")

    # calcola nuovo TOTAL
    new_total_val = old_total_val
    new_total_var = old_total_err ** 2
    for term in terms:
        ov, oe = old_values[term]
        nv, ne = new_values[term]
        new_total_val += nv - ov
        new_total_var += ne ** 2 - oe ** 2
    new_total_err = math.sqrt(max(0.0, new_total_var))
    src = "txt" if txt_loaded else "summary row"
    print(f"  {'TOTAL':20s}: {old_total_val:.6g} ± {old_total_err:.6g}  →  {new_total_val:.6g} ± {new_total_err:.6g}  (da {src})")

    # trova tutti i blocchi Vegas sul testo originale PRIMA di modificarlo:
    # cosi gli offset sono consistenti e il dry-run vede gli stessi errori del run reale.
    # I termini con block_text=None (Gauss) aggiornano solo i numeri, nessun blocco da sostituire.
    block_positions = {}  # term -> (vstart, vend), solo termini Vegas
    for term in terms:
        if new_blocks[term] is None:
            col_name = TERM_TO_COLUMN[term]
            print(f"  {col_name:20s}: quadratura Gauss, solo aggiornamento numeri")
            continue  # Gauss: nessun blocco Vegas da sostituire
        vstart, vend = find_vegas_block(full_text, term)
        if vstart is None:
            print(f"  [WARN] blocco Vegas '{term}' non trovato in {full_path}, skip gruppo")
            return False
        block_positions[term] = (vstart, vend)

    if dry_run:
        return True

    if backup and os.path.exists(full_path):
        shutil.copy2(full_path, full_path + ".bak")
    if backup and txt_path and os.path.exists(txt_path):
        shutil.copy2(txt_path, txt_path + ".bak")

    # applica in ordine inverso (dal fondo); solo termini Vegas
    replacements = sorted(block_positions.items(), key=lambda x: x[1][0], reverse=True)
    patched = full_text
    for term, (vstart, vend) in replacements:
        patched = patched[:vstart] + new_blocks[term] + patched[vend:]

    # aggiorna summary row per tutti i termini cambiati + TOTAL
    for term in terms:
        col_idx = column_index_for_term(term, order)
        nv, ne = new_values[term]
        patched = update_summary_row_full(
            patched, col_idx, n_data_cols,
            nv, ne,
            new_total_val, new_total_err,
        )

    # aggiorna footer "Total cross section"
    patched = re.sub(
        r"(Total cross section\s+)([-+]?\d[\d\.\s±eE+\-·⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+)(fb|pb)",
        lambda m: (
            f"{m.group(1)}"
            f"{new_total_val:>12.6g} ± {new_total_err:<10.6g}"
            f"{m.group(3)}"
        ),
        patched,
    )

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        f.write(patched)
    print(f"  Scritto: {out_path}")

    _write_txt(txt_path, new_total_val, new_total_err, out_path.replace(".log", ".txt"))
    return True


def patch_term_in_full_log(partial_path, full_path, out_path, txt_path,
                            term, order, dry_run=False, backup=False):
    """
    CASO A: sostituisce il blocco del termine nel log completo.
    Scrive il risultato in out_path (es. <nome>_patched.log).
    """
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}[CASO A] patch '{term}' in log completo")
    print(f"  partial : {partial_path}")
    print(f"  full    : {full_path}")
    print(f"  output  : {out_path}")

    new_block, new_val, new_err = extract_partial_block(partial_path, term)
    if new_block is None:
        print(f"  [WARN] impossibile estrarre il blocco '{term}' da {partial_path}, skip")
        return False
    print(f"  Nuovo {term}: {new_val:.6g} ± {new_err:.6g}")

    with open(full_path, "r", errors="replace") as f:
        full_text = f.read()

    # estrai summary corrente
    summary = extract_full_summary(full_text)
    cols = FULL_COLUMNS.get(order, FULL_COLUMNS["NNLL"])
    n_data_cols = len(cols) - 1  # escludi TOTAL

    if len(summary) != n_data_cols + 1:
        print(f"  [WARN] summary row ha {len(summary)} valori, attesi {n_data_cols + 1}, skip")
        return False

    col_idx = column_index_for_term(term, order)
    if col_idx is None:
        print(f"  [WARN] termine '{term}' non trovato nelle colonne di {order}, skip")
        return False

    old_val, old_err       = summary[col_idx]
    old_total_val, old_total_err = summary[-1]
    print(f"  Vecchio {term}: {old_val:.6g} ± {old_err:.6g}")

    # leggi total ad alta precisione dal .txt esistente (se c'è)
    txt_loaded = False
    if txt_path and os.path.exists(txt_path):
        with open(txt_path) as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#"):
                    parts = s.split()
                    if len(parts) >= 2:
                        try:
                            old_total_val = float(parts[0])
                            old_total_err = float(parts[1])
                            txt_loaded = True
                            break
                        except ValueError:
                            continue  # riga non numerica, salta
    if txt_loaded:
        print(f"  Old TOTAL (txt): {old_total_val:.15g} ± {old_total_err:.15g}")
    else:
        print(f"  [INFO] .txt non trovato o non leggibile, uso total dalla summary row")

    # nuovo total
    new_total_val = old_total_val - old_val + new_val
    new_total_err = math.sqrt(max(0.0, old_total_err**2 - old_err**2 + new_err**2))
    print(f"  New TOTAL: {new_total_val:.15g} ± {new_total_err:.15g}")

    if dry_run:
        return True

    if backup and os.path.exists(full_path):
        shutil.copy2(full_path, full_path + ".bak")
    if backup and os.path.exists(txt_path):
        shutil.copy2(txt_path, txt_path + ".bak")

    # sostituisce il blocco Vegas nel log completo
    vstart, vend = find_vegas_block(full_text, term)
    if vstart is None:
        print(f"  [WARN] blocco Vegas '{term}' non trovato in {full_path}, skip")
        return False
    patched = full_text[:vstart] + new_block + full_text[vend:]

    # aggiorna summary row
    patched = update_summary_row_full(
        patched, col_idx, n_data_cols,
        new_val, new_err,
        new_total_val, new_total_err,
    )

    # aggiorna "Total cross section" footer
    patched = re.sub(
        r"(Total cross section\s+)([-+]?\d[\d\.\s±eE+\-·⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+)(fb|pb)",
        lambda m: (
            f"{m.group(1)}"
            f"{new_total_val:>12.6g} ± {new_total_err:<10.6g}"
            f"{m.group(3)}"
        ),
        patched,
    )

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        f.write(patched)
    print(f"  Scritto: {out_path}")

    # aggiorna .txt
    _write_txt(txt_path, new_total_val, new_total_err, out_path.replace(".log", ".txt"))

    return True


# -------------------------------------------------------
# CASO B — assemblaggio log sintetico
# -------------------------------------------------------

def _header_from_partial(partial_text):
    """
    Estrae l'header di un log parziale (tutto fino alla prima ┏),
    che riutilizziamo nel log sintetico.
    """
    pos = partial_text.find("┏")
    if pos == -1:
        return ""
    # torna all'inizio della riga
    line_start = partial_text.rfind("\n", 0, pos)
    return partial_text[:line_start + 1] if line_start != -1 else partial_text[:pos]


def _box_row(cells, col_width=34, sep="┃", corner_l="┃", corner_r="┃"):
    """Costruisce una riga della tabella con celle di larghezza fissa."""
    parts = [f"{corner_l}"]
    for i, cell in enumerate(cells):
        parts.append(f"{cell:^{col_width}}")
        parts.append(sep if i < len(cells) - 1 else corner_r)
    return "".join(parts)


def _box_separator(n_cols, col_width=34, left="┣", mid="╋", right="┫", h="━"):
    seg = h * col_width
    return left + (mid.join([seg] * n_cols)) + right


def _box_top(n_cols, col_width=34):
    seg = "━" * col_width
    return "┏" + "┰".join([seg] * n_cols) + "┓"


def _box_bottom(n_cols, col_width=34):
    seg = "━" * col_width
    return "┗" + "┻".join([seg] * n_cols) + "┛"


def build_synthetic_log(group_key, partial_logs, out_path, txt_path, dry_run=False):
    """
    CASO B: assembla un log sintetico da N log parziali.
    group_key = (prefix, order, muR, muF, muQ, muR_str, muF_str, muQ_str)
    partial_logs = { term: path }  (es. {"BORN": "...", "CT": "...", ...})

    Struttura del log sintetico:
        - header preso dal log parziale BORN (o il primo disponibile)
        - Integration settings minimale
        - Constant boundaries (dal primo parziale)
        - tabella a N+1 colonne (termini + TOTAL)
          ogni cella contiene il blocco Vegas completo (header+iter+risultato)
        - summary row
        - footer con TOTAL
    """
    prefix, order, muR, muF, muQ, muR_str, muF_str, muQ_str = group_key
    cols_all = FULL_COLUMNS.get(order, FULL_COLUMNS["NNLL"])
    data_cols = [c for c in cols_all if c != "TOTAL"]  # es. ["Resummation","Counter term","V+J Real","V+J Virtual"]

    # mappa colonna → termine
    col_to_term = {v: k for k, v in TERM_TO_COLUMN.items()}

    print(f"\n{'[DRY-RUN] ' if dry_run else ''}[CASO B] assembla log sintetico")
    print(f"  gruppo  : {prefix}_{order}_muR{muR:g}_muF{muF:g}_muQ{muQ:g}")
    print(f"  termini : {list(partial_logs.keys())}")
    print(f"  output  : {out_path}")

    # estrai blocchi e valori
    blocks = {}  # colonna → block_text
    values = {}  # colonna → (val, err)
    for col in data_cols:
        term = col_to_term.get(col)
        if term is None or term not in partial_logs:
            print(f"  [WARN] colonna '{col}' (termine '{term}') non disponibile")
            blocks[col] = f"  (mancante)  "
            values[col] = (0.0, 0.0)
            continue
        path = partial_logs[term]
        block_text, val, err = extract_partial_block(path, term)
        if val is None:
            # errore reale: né Vegas né Gauss ha prodotto un risultato
            print(f"  [WARN] impossibile leggere il risultato '{term}' da {path}")
            blocks[col] = None
            values[col] = (0.0, 0.0)
        else:
            # block_text=None è legittimo per quadratura Gauss
            blocks[col] = block_text
            values[col] = (val, err)
            gauss_note = " (Gauss)" if block_text is None else ""
            print(f"  {col:20s}: {val:.6g} ± {err:.6g}{gauss_note}")

    # calcola TOTAL
    total_val = sum(v for v, _ in values.values())
    total_err = math.sqrt(sum(e**2 for _, e in values.values()))
    print(f"  {'TOTAL':20s}: {total_val:.15g} ± {total_err:.15g}")

    if dry_run:
        return True

    # --- header: prendi dal primo parziale disponibile ---
    header_source = partial_logs.get("BORN") or next(iter(partial_logs.values()))
    with open(header_source, "r", errors="replace") as f:
        src_text = f.read()
    header = _header_from_partial(src_text)

    # --- constant boundaries (estratto dal primo parziale disponibile) ---
    # (già incluso nell'header sopra, ma lo lasciamo per chiarezza)

    # --- costruzione tabella ---
    n_cols = len(data_cols) + 1  # +1 per TOTAL
    col_width = 34

    # header tabella
    table_lines = []
    table_lines.append(_box_top(n_cols, col_width))
    header_cells = data_cols + ["TOTAL"]
    table_lines.append(_box_row(header_cells, col_width))
    table_lines.append(_box_separator(n_cols, col_width))

    # riga dati: i blocchi Vegas vanno nella prima cella (stile DYTurbo)
    # In un log completo DYTurbo ogni blocco Vegas è nella cella della tabella,
    # separato solo da ┃ (senza a capo rigido).
    # Riproduciamo: ┃<blocco_col0>┃<blocco_col1>┃...┃<risultato_TOTAL>┃
    # Il blocco di ogni colonna termina con il suo risultato finale seguito da " ┃"

    # assembla la riga dati principale
    # ogni blocco parziale termina già con " val ± err (time) " ma senza ┃ finale
    # (il ┃ è il separatore di cella e viene aggiunto qui)
    row_parts = ["┃"]
    for col in data_cols:
        val, err = values[col]
        if blocks[col] is None:
            # Gauss/cuhre: nessun blocco Vegas, solo il valore finale
            row_parts.append(f"  {fmt_val_err(val, err, width=6, time_str='0s')}")
        else:
            block = blocks[col].rstrip("\n").rstrip("┃").rstrip()
            row_parts.append(block)
        row_parts.append(" ┃")

    # colonna TOTAL: solo il valore finale (nessun blocco Vegas per il TOTAL)
    # usa time_str="0s" per compatibilità con RESULT_RE del parser
    total_cell = f"     {fmt_val_err(total_val, total_err, width=6, time_str='0s')}"
    row_parts.append(total_cell)
    row_parts.append("┃\n")

    table_lines.append("".join(row_parts))
    table_lines.append(_box_separator(n_cols, col_width))

    # summary row: stessi valori già presenti nei blocchi parziali,
    # riformattati in modo compatto e compatibile con RESULT_RE
    summary_cells = []
    for col in data_cols:
        val, err = values[col]
        summary_cells.append(f" {fmt_val_err(val, err, width=6, time_str='0s')} ")
    summary_cells.append(f" {fmt_val_err(total_val, total_err, width=6, time_str='0s')} ")
    table_lines.append(_box_row(summary_cells, col_width))
    table_lines.append(_box_bottom(n_cols, col_width))

    # footer
    footer = (
        f"\n╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍ Summary ╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍\n"
        f"      Total cross section         {total_val:>15.6g} ± {total_err:<10.6g} fb\n"
        f"              Output file         {out_path.replace('.log', '.root')}\n"
        f"      Result in text file         {txt_path}\n"
        f"╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍\n"
    )

    # assembla il log sintetico
    synthetic = header + "\n".join(table_lines) + footer

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        f.write(synthetic)
    print(f"  Scritto log sintetico: {out_path}")

    _write_txt(txt_path, total_val, total_err, txt_path)

    return True


# -------------------------------------------------------
# scrittura .txt
# -------------------------------------------------------

def _write_txt(old_txt_path, total_val, total_err, out_txt_path):
    """Scrive (o sovrascrive) il .txt con TOTAL e errore."""
    # cerca header dal vecchio .txt se esiste
    header_line = "#PDF0  uncertainty\n"
    if os.path.exists(old_txt_path):
        with open(old_txt_path) as f:
            for line in f:
                if line.strip().startswith("#"):
                    header_line = line
                    break

    content = (
        f"{header_line}"
        f"{total_val} {total_err}\n"
        f"{total_val} {total_err}\n"
    )
    os.makedirs(os.path.dirname(out_txt_path) or ".", exist_ok=True)
    with open(out_txt_path, "w") as f:
        f.write(content)
    print(f"  Scritto txt: {out_txt_path}")


# -------------------------------------------------------
# scansione e raggruppamento dei log parziali
# -------------------------------------------------------

def scan_partial_dir(directory):
    """
    Scansiona directory e raggruppa i log parziali (quelli con _TERM_ nel nome)
    per (prefix, order, muR, muF, muQ) → { term: path }.
    I log completi (senza _TERM_) vengono ignorati qui — li si cerca
    per nome nel main quando si decide Caso A vs Caso B.
    """
    groups = defaultdict(dict)
    skipped = []

    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".log"):
            continue
        # salta file già prodotti da questo script
        if "_patched" in fname:
            continue
        info = parse_partial_filename(fname)
        if info is None:
            skipped.append(fname)
            continue
        key = (info["prefix"], info["order"],
               info["muR"], info["muF"], info["muQ"],
               info["muR_str"], info["muF_str"], info["muQ_str"])
        groups[key][info["term"]] = os.path.join(directory, fname)

    if skipped:
        print(f"\n[INFO] {len(skipped)} file ignorati (log completi o nome non riconosciuto "
              f"come parziale — normale).")

    return groups


# -------------------------------------------------------
# main
# -------------------------------------------------------

def main():
    directory = args.directory

    if not os.path.isdir(directory):
        print(f"[ERRORE] '{directory}' non è una directory valida.")
        raise SystemExit(1)

    groups = scan_partial_dir(directory)
    print(f"\nTrovati {len(groups)} gruppo/i di log parziali in '{directory}'.")

    n_caseA = 0
    n_caseB = 0
    n_warn  = 0
    n_skip  = 0

    for group_key, partial_logs in sorted(groups.items()):
        prefix, order, muR, muF, muQ, muR_str, muF_str, muQ_str = group_key
        full_name = full_log_name(prefix, order, muR, muF, muQ)
        txt_name  = full_txt_name(prefix, order, muR, muF, muQ)
        # cerca su disco con tutte le varianti di rappresentazione delle scale
        full_path = _find_full_file(directory, prefix, order, muR, muF, muQ, ".log")
        txt_path  = _find_full_file(directory, prefix, order, muR, muF, muQ, ".txt")                     or os.path.join(directory, txt_name)
        # per Caso B, output path canonico
        full_path_out = full_path or os.path.join(directory, full_name)

        # -------------------------------------------------------
        # determina i termini attesi per questo ordine
        # -------------------------------------------------------
        if order == "NLL":
            expected_terms = set(ALL_TERMS_NLL)   # {"BORN", "CT"}
        else:
            expected_terms = set(ALL_TERMS_NNLL)  # {"BORN", "CT", "VJREAL", "VJVIRT"}

        available_terms = set(partial_logs.keys())

        # -------------------------------------------------------
        # CASO A — log completo esiste nella stessa directory
        # -------------------------------------------------------
        if full_path is not None:
            actual_full_name = os.path.basename(full_path)
            out_name = actual_full_name  # sovrascrive il log originale
            out_path = os.path.join(directory, out_name)
            out_txt  = full_path.replace(".log", ".txt")
            ok = patch_terms_in_full_log(
                partial_logs, full_path, out_path, txt_path,
                order,
                dry_run=args.dry_run,
                backup=args.backup,
            )
            if ok:
                n_caseA += 1
            else:
                n_skip += 1
                n_warn += 1

        # -------------------------------------------------------
        # CASO B — log completo NON esiste
        # -------------------------------------------------------
        else:
            # NLL: impossibile assemblare (VJ non esiste come parziale)
            if order == "NLL":
                print(
                    f"\n{'=' * 70}\n"
                    f"  ⚠ WARNING: gruppo NLL senza log completo — SKIP\n"
                    f"    {prefix}_{order}_muR{muR:g}_muF{muF:g}_muQ{muQ:g}\n"
                    f"    Per NLL il V+J non esiste come pezzo standalone;\n"
                    f"    il log completo dovrebbe essere nella stessa directory.\n"
                    f"{'=' * 70}"
                )
                n_warn += 1
                n_skip += 1
                continue

            # controlla termini mancanti — se mancano, skip senza output
            missing = expected_terms - available_terms
            if missing:
                print(
                    f"\n{'=' * 70}\n"
                    f"  ⚠ WARNING: pezzi mancanti — SKIP, nessun output prodotto\n"
                    f"    gruppo  : {prefix}_{order}_muR{muR:g}_muF{muF:g}_muQ{muQ:g}\n"
                    f"    attesi  : {sorted(expected_terms)}\n"
                    f"    trovati : {sorted(available_terms)}\n"
                    f"    mancano : {sorted(missing)}\n"
                    f"{'=' * 70}"
                )
                n_warn += 1
                n_skip += 1
                continue

            # assembla con tutti i pezzi disponibili (completo)
            assembled_name = assembled_log_name(prefix, order, muR, muF, muQ, muR_str, muF_str, muQ_str)
            assembled_txt  = assembled_txt_name(prefix, order, muR, muF, muQ, muR_str, muF_str, muQ_str)
            out_path = os.path.join(directory, assembled_name)
            out_txt  = os.path.join(directory, assembled_txt)
            ok = build_synthetic_log(
                group_key, partial_logs,
                out_path, out_txt,
                dry_run=args.dry_run,
            )
            if ok:
                n_caseB += 1
            else:
                n_skip += 1
                n_warn += 1

    print(
        f"\n{'=' * 70}\n"
        f"  {'[DRY-RUN] ' if args.dry_run else ''}Riepilogo:\n"
        f"    Caso A (patch log completo) : {n_caseA}\n"
        f"    Caso B (log sintetico)      : {n_caseB}\n"
        f"    Warning                     : {n_warn}\n"
        f"    Skip                        : {n_skip}\n"
        f"{'=' * 70}"
    )


if __name__ == "__main__":
    main()