#!/bin/bash

set -e


SOURCE_FILE="./networks/filtered/ohare-filtered.osm.xml"
OUTPUT_PATH="./sumo/simulations/ohare-chicago"

chmod -R a+rw "$SOURCE_FILE"

BASENAME=$(basename "$SOURCE_FILE" .osm.xml)
TARGET_FILE="${OUTPUT_PATH}/${BASENAME}.net.xml"

export SUMO_HOME="/usr/share/sumo"

# use sumo netconvert tool to convert the osm file to a sumo network file
netconvert --osm-files $SOURCE_FILE -o $TARGET_FILE \
    --ramps.guess \
    --junctions.join \
    --tls.guess-signals \
    --tls.discard-simple \
    --tls.join \
    --tls.default-type actuated \
    -t $SUMO_HOME/data/typemap/osmNetconvert.typ.xml \
    --remove-edges.by-vclass rail,rail_fast,bicycle,pedestrian\
    --remove-edges.isolated \
    --output.street-names true \
    --output.original-names true 