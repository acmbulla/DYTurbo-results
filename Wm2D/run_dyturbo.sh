#!/bin/bash

export VO_CMS_SW_DIR=/cvmfs/cms.cern.ch
source ${VO_CMS_SW_DIR}/cmsset_default.sh

cd /gwpool/users/abulla/DYTurbo/CMSSW_14_0_21/src || exit 1
eval `scramv1 runtime -sh`

cd /gwpool/users/abulla/DYTurbo/dyturbo-1.4.2-empire/DYZ/Wm2D  || exit 1

./../../bin/dyturbo "$1"