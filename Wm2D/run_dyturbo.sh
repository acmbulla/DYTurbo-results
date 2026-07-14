#!/bin/bash

echo "Starting DYTurbo job"
hostname
pwd
ls

# -------------------------
# CMS environment
# -------------------------

source /cvmfs/cms.cern.ch/cmsset_default.sh

export SCRAM_ARCH=el9_amd64_gcc12

cmsrel CMSSW_14_0_21
cd CMSSW_14_0_21/src

cmsenv

cd -

# unpack
tar -xzf dyturbo-1.4.2-empire.tar.gz || exit 1
rm dyturbo-1.4.2-empire.tar.gz

cd dyturbo-1.4.2-empire || exit 1

# environment
# source source.sh || exit 1

# build
# ./configure --enable-root --enable-Ofast || exit 1
# make install -j 4 || exit 1

## storing the results in a separate directory to avoid copying the whole area back to eos
mkdir outputs
mkdir tmp_outputs

INPUT=$(find .. -maxdepth 1 -name "*mu*.in" | head -n 1)
cp "$INPUT" .
INPUT_BASENAME=$(basename "$INPUT")

EOS_OUT=root://eosuser.cern.ch//eos/user/a/abulla/CMSSW_14_0_21/src/dyturbo-1.4.2-empire/DYZ/DYTurbo-results/Wm2D/outputs

STATEFILE=$(grep -E '^\s*statefile\s*=' "$INPUT_BASENAME" | sed 's/.*=\s*//' | tr -d ' \r')
FLAGSEXTRA=$(grep -E '^\s*vegasFlagsExtra\s*=' "$INPUT_BASENAME" | sed 's/.*=\s*//' | tr -d ' \r')

# --- scarico la griglia se questo config ne referenzia una ---
# (per il nominale non esiste ancora la prima volta: fallisce silenziosamente,
#  parte a freddo; per una variazione, la trova gia' scritta dal nominale)
if [ -n "$STATEFILE" ]; then
    xrdcp -f "${EOS_OUT}/${STATEFILE}" . 2>/dev/null \
        && echo "Griglia trovata e scaricata: ${STATEFILE}" \
        || echo "Nessuna griglia esistente per ${STATEFILE} (parto a freddo)"
fi

./bin/dyturbo "$INPUT_BASENAME" || exit 1

# output copy
xrdcp -f outputs/*.log "${EOS_OUT}/" || exit 1
xrdcp -f outputs/*.txt "${EOS_OUT}/" || exit 1

# griglia: la ripubblico SOLO se sono il nominale (flags=16, "retain" ma non
# "reset-keep-grid"). Le variazioni (flags=48) la leggono ma NON la
# riscrivono indietro, cosi' non contaminano la griglia condivisa per le
# variazioni successive dello stesso bin.
if [ "$FLAGSEXTRA" = "16" ] && compgen -G "*.state" > /dev/null; then
    xrdcp -f *.state "${EOS_OUT}/" || exit 1
fi