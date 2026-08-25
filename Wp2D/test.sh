#!/bin/bash

OUTDIR="outputs"

declare -A PATHOLOGICAL_BINS
PATHOLOGICAL_BINS["0_2"]="44 46 48 50 52 54 56 58"
PATHOLOGICAL_BINS["2_4"]="46 48 50 52 54 56 58"
PATHOLOGICAL_BINS["4_6"]="46 48 50 52 54 56 58"
PATHOLOGICAL_BINS["6_8"]="48 50 52 54 56 58"
PATHOLOGICAL_BINS["8_10"]="48 50 52 54 56 58"
PATHOLOGICAL_BINS["10_12"]="50 52 54 56 58"
PATHOLOGICAL_BINS["12_14"]="50 52 54 56 58"
PATHOLOGICAL_BINS["14_16"]="52 54 56 58"
PATHOLOGICAL_BINS["16_18"]="54 56 58"
PATHOLOGICAL_BINS["18_20"]="54 56 58"
PATHOLOGICAL_BINS["20_22"]="54 56 58"
PATHOLOGICAL_BINS["22_24"]="56 58"
PATHOLOGICAL_BINS["24_26"]="58"
PATHOLOGICAL_BINS["26_28"]="58"

for qt_tag in "${!PATHOLOGICAL_BINS[@]}"; do
    for ptl_low in ${PATHOLOGICAL_BINS[$qt_tag]}; do
        ptl_high=$((ptl_low + 2))
        for order in NNLL N3LL; do
            pattern="${OUTDIR}/*_qt_qt${qt_tag}_ptl${ptl_low}_${ptl_high}_${order}_*.{root,txt,log,state}"
            for f in ${OUTDIR}/*_qt_qt${qt_tag}_ptl${ptl_low}_${ptl_high}_${order}_*.root \
                     ${OUTDIR}/*_qt_qt${qt_tag}_ptl${ptl_low}_${ptl_high}_${order}_*.txt \
                     ${OUTDIR}/*_qt_qt${qt_tag}_ptl${ptl_low}_${ptl_high}_${order}_*.log \
                     ${OUTDIR}/*_qt_qt${qt_tag}_ptl${ptl_low}_${ptl_high}_${order}*.state; do
                if [ -f "$f" ]; then
                    echo "Removing $f"
                    rm "$f"
                fi
            done
        done
    done
done