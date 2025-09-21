#!/bin/bash

set -e

TAZ_FILE="./sumo/simulations/ohare-chicago/ohare-filtered.taz.add.xml"  
OUTPUT_PATH="./sumo/simulations/ohare-chicago"

chmod -R a+rw "$TAZ_FILE"

BASENAME=$(basename "$TAZ_FILE" .taz.add.xml)
OD_MATRIX_OUTPUT_FILE="${OUTPUT_PATH}/${BASENAME}.od"
TRIPS_OUTPUT_FILE="${OUTPUT_PATH}/${BASENAME}.trips.xml"

touch $OD_MATRIX_OUTPUT_FILE
touch $TRIPS_OUTPUT_FILE

export SUMO_HOME="/usr/share/sumo"

od2trips -v \
    --taz-files $TAZ_FILE \
    -o $TRIPS_OUTPUT_FILE \
    --od-matrix-files $OD_MATRIX_OUTPUT_FILE \
    --vtype passenger \
    --prefix car 
