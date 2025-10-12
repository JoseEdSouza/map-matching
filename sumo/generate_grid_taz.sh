#!/bin/bash

set -e

NETWORK_FILE="./sumo/simulations/ohare-chicago-junctionless/network.net.xml"
OUTPUT_PATH="./sumo/simulations/ohare-chicago-junctionless"

chmod -R a+rw "$NETWORK_FILE"

OUTPUT_FILE="${OUTPUT_PATH}/grid_taz.add.xml"

export SUMO_HOME="/usr/share/sumo"

python3 $SUMO_HOME/tools/district/gridDistricts.py \
    --verbose \
    -n $NETWORK_FILE \
    -o $OUTPUT_FILE \
    --grid-width 200 \
    --seed 42 