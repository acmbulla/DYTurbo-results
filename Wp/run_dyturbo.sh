#!/bin/bash

cd /gwpool/users/abulla/DYTurbo/dyturbo-1.4.2 || exit 1

# ROOT
# source /cvmfs/sft.cern.ch/lcg/views/LCG_106/x86_64-el9-gcc13-opt/setup.sh

# DYTurbo env
source source.sh

cd /gwpool/users/abulla/DYTurbo/dyturbo-1.4.2/DYZ/Wp || exit 1

./../../bin/dyturbo "$1"