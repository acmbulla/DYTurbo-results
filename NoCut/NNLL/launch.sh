#!/bin/bash

CONFIG=process.in

# export PATH=/cvmfs/sft.cern.ch/lcg/releases/MCGenerators/lhapdf/6.5.3-3fa11/x86_64-centos9-gcc11-opt/bin:$PATH
DYT=/gwpool/users/abulla/DYTurbo/dyturbo-1.4.2/bin/dyturbo
# export LHAPDF_DATA_PATH=/cvmfs/sft.cern.ch/lcg/external/lhapdfsets/current/:/cvmfs/sft.cern.ch/lcg/releases/MCGenerators/lhapdf/6.5.3-3fa11/x86_64-centos8-gcc11-opt/share/LHAPDF

# scale variations (7-point)
scales=(
"1.0 1.0"
"2.0 1.0"
"0.5 1.0"
"1.0 2.0"
"1.0 0.5"
"2.0 2.0"
"0.5 0.5"
)

# orders: NLL and NNLL
orders=(
"2 NNLL"
)

for ord in "${orders[@]}"; do
    read order label <<< $ord

    i=0
    for s in "${scales[@]}"; do
        read kmuren kmufac <<< $s

        tag=${label}_muR${kmuren}_muF${kmufac}

        echo "Launching $tag"

        $DYT $CONFIG \
            --order $order \
            --kmuren $kmuren \
            --kmufac $kmufac \
            --kmures 1.0 \
            --ofname out_${tag} &

        ((i++))
    done
done

wait