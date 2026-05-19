#!/usr/bin/env python3.11
"""
Estrae dati da 1D.root e 2D.root e li salva come griglie pandas (Parquet).

Sorgenti:
  - 1D.root : {Z,Wp,Wm}/{order}/qt/{variation}          → TH1D in qt
  - 2D.root : {Wp2D,Wm2D}/{order}/qt_ptl/{variation}    → TH2D (qt × ptl)
              {Wp2D,Wm2D}/{order}/qt_ptl/{variation}_proj_qt   → TH1D proj qt
              {Wp2D,Wm2D}/{order}/qt_ptl/{variation}_proj_ptl  → TH1D proj ptl

I valori (value, error) sono sezioni d'urto integrate sul rispettivo bin [pb].

Output in grids/:
  dyturbo_1d.parquet        boson, order, muF, muQ, muR, qt_lo, qt_hi, qt_center, value, error
  dyturbo_2d_wp.parquet     boson, order, muF, muQ, muR, qt_lo, qt_hi, ptl_lo, ptl_hi, value, error
  dyturbo_2d_wm.parquet     (stessa struttura)
  dyturbo_proj_qt.parquet   boson, order, muF, muQ, muR, qt_lo, qt_hi, qt_center, value, error
  dyturbo_proj_ptl.parquet  boson, order, muF, muQ, muR, ptl_lo, ptl_hi, ptl_center, value, error
"""

import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import uproot

warnings.filterwarnings("ignore", category=FutureWarning)

BASE   = Path(__file__).parent
FILE1D = BASE / "1D.root"
FILE2D = BASE / "2D.root"
OUT    = BASE / "grids"
OUT.mkdir(exist_ok=True)

ORDERS = ("NLL", "NNLL", "N3LL")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _scales(name: str) -> tuple[float, float, float]:
    """'muF0p5_muQ2p0_muR1p0' → (muF, muQ, muR).  'nominal' → (1, 1, 1)."""
    if name == "nominal":
        return 1.0, 1.0, 1.0
    def _v(tag):
        m = re.search(rf"{tag}(\d+)p(\d+)", name)
        return float(f"{m.group(1)}.{m.group(2)}")
    return _v("muF"), _v("muQ"), _v("muR")


def _th1d_to_rows(h, base: dict) -> list[dict]:
    values, edges = h.to_numpy()
    errors  = np.sqrt(h.variances())
    centers = 0.5 * (edges[:-1] + edges[1:])
    return [
        {**base,
         "qt_lo": float(edges[i]), "qt_hi": float(edges[i+1]),
         "qt_center": float(centers[i]),
         "value": float(values[i]), "error": float(errors[i])}
        for i in range(len(values))
    ]


def _th1d_ptl_to_rows(h, base: dict) -> list[dict]:
    values, edges = h.to_numpy()
    errors  = np.sqrt(h.variances())
    centers = 0.5 * (edges[:-1] + edges[1:])
    return [
        {**base,
         "ptl_lo": float(edges[i]), "ptl_hi": float(edges[i+1]),
         "ptl_center": float(centers[i]),
         "value": float(values[i]), "error": float(errors[i])}
        for i in range(len(values))
    ]


def _th2d_to_rows(h, base: dict) -> list[dict]:
    values, xedges, yedges = h.to_numpy()
    errors = np.sqrt(h.variances())
    rows = []
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            rows.append({
                **base,
                "qt_lo" : float(xedges[i]),   "qt_hi" : float(xedges[i+1]),
                "ptl_lo": float(yedges[j]),   "ptl_hi": float(yedges[j+1]),
                "value" : float(values[i, j]),
                "error" : float(errors[i, j]),
            })
    return rows


# ── Estrazione ────────────────────────────────────────────────────────────────

def extract_1d() -> pd.DataFrame:
    rows = []
    with uproot.open(str(FILE1D)) as f:
        for boson in ("Z", "Wp", "Wm"):
            for order in ORDERS:
                qt_dir = f[boson][order]["qt"]
                for key in qt_dir.keys():
                    name = key.rstrip(";1")
                    muF, muQ, muR = _scales(name)
                    base = {"boson": boson, "order": order,
                            "muF": muF, "muQ": muQ, "muR": muR}
                    rows.extend(_th1d_to_rows(qt_dir[name], base))

    return (pd.DataFrame(rows)
            .astype({"boson": "category", "order": "category"})
            .sort_values(["boson", "order", "muR", "muF", "muQ", "qt_lo"])
            .reset_index(drop=True))


def extract_2d(boson: str) -> pd.DataFrame:
    rows = []
    key2d = f"{boson}2D"
    with uproot.open(str(FILE2D)) as f:
        for order in ORDERS:
            qt_ptl = f[key2d][order]["qt_ptl"]
            th2d_keys = [k.rstrip(";1") for k in qt_ptl.keys()
                         if not k.rstrip(";1").endswith(("_proj_qt", "_proj_ptl"))]
            for name in th2d_keys:
                muF, muQ, muR = _scales(name)
                base = {"boson": boson, "order": order,
                        "muF": muF, "muQ": muQ, "muR": muR}
                rows.extend(_th2d_to_rows(qt_ptl[name], base))

    return (pd.DataFrame(rows)
            .astype({"boson": "category", "order": "category"})
            .sort_values(["boson", "order", "muR", "muF", "muQ", "qt_lo", "ptl_lo"])
            .reset_index(drop=True)
            [["boson", "order", "muF", "muQ", "muR",
              "qt_lo", "qt_hi", "ptl_lo", "ptl_hi", "value", "error"]])


def extract_projections() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows_qt, rows_ptl = [], []
    with uproot.open(str(FILE2D)) as f:
        for boson_tag in ("Wp2D", "Wm2D"):
            boson = boson_tag.replace("2D", "")
            for order in ORDERS:
                qt_ptl = f[boson_tag][order]["qt_ptl"]
                all_keys = [k.rstrip(";1") for k in qt_ptl.keys()]
                proj_qt_keys  = [k for k in all_keys if k.endswith("_proj_qt")]
                proj_ptl_keys = [k for k in all_keys if k.endswith("_proj_ptl")]

                for pkey in proj_qt_keys:
                    name = pkey.replace("_proj_qt", "")
                    muF, muQ, muR = _scales(name)
                    base = {"boson": boson, "order": order,
                            "muF": muF, "muQ": muQ, "muR": muR}
                    rows_qt.extend(_th1d_to_rows(qt_ptl[pkey], base))

                for pkey in proj_ptl_keys:
                    name = pkey.replace("_proj_ptl", "")
                    muF, muQ, muR = _scales(name)
                    base = {"boson": boson, "order": order,
                            "muF": muF, "muQ": muQ, "muR": muR}
                    rows_ptl.extend(_th1d_ptl_to_rows(qt_ptl[pkey], base))

    def _clean(rows, sort_col):
        return (pd.DataFrame(rows)
                .astype({"boson": "category", "order": "category"})
                .sort_values(["boson", "order", "muR", "muF", "muQ", sort_col])
                .reset_index(drop=True))

    return _clean(rows_qt, "qt_lo"), _clean(rows_ptl, "ptl_lo")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Estrazione 1D (da 1D.root)...")
    df1d = extract_1d()
    df1d.to_parquet(OUT / "dyturbo_1d.parquet", index=False)
    print(f"  {OUT/'dyturbo_1d.parquet'}  [{len(df1d):,} righe]")
    print(df1d.groupby(["boson", "order"])["value"].count().unstack().to_string())
    print()

    for boson in ("Wp", "Wm"):
        print(f"Estrazione 2D {boson} (da 2D.root)...")
        df2d = extract_2d(boson)
        out  = OUT / f"dyturbo_2d_{boson.lower()}.parquet"
        df2d.to_parquet(out, index=False)
        print(f"  {out}  [{len(df2d):,} righe]")
        print(f"  qt: [{df2d.qt_lo.min()}, {df2d.qt_hi.max()}] GeV  "
              f"ptl: [{df2d.ptl_lo.min()}, {df2d.ptl_hi.max()}] GeV")
        print()

    print("Estrazione proiezioni (da 2D.root)...")
    df_pqt, df_pptl = extract_projections()
    df_pqt.to_parquet(OUT / "dyturbo_proj_qt.parquet", index=False)
    df_pptl.to_parquet(OUT / "dyturbo_proj_ptl.parquet", index=False)
    print(f"  proj_qt :  {OUT/'dyturbo_proj_qt.parquet'}   [{len(df_pqt):,} righe]")
    print(f"  proj_ptl:  {OUT/'dyturbo_proj_ptl.parquet'}  [{len(df_pptl):,} righe]")
    print()
    print(df_pqt.groupby(["boson", "order"])["value"].count().unstack().to_string())
