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

./bin/dyturbo "$(basename "$INPUT")" || exit 1

# output copy
xrdcp -f outputs/*.log root://eosuser.cern.ch//eos/user/a/abulla/CMSSW_14_0_21/src/dyturbo-1.4.2-empire/DYZ/DYTurbo-results/Wm2D/outputs/ \
|| exit 1

xrdcp -f outputs/*.txt root://eosuser.cern.ch//eos/user/a/abulla/CMSSW_14_0_21/src/dyturbo-1.4.2-empire/DYZ/DYTurbo-results/Wm2D/outputs/ \
|| exit 1