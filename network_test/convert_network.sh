#!/bin/bash

set -e


SOURCE_FILE="./network_test/ohare-filtered.osm.xml"
OUTPUT_PATH="./network_test"

chmod -R a+rw "$SOURCE_FILE"

TARGET_FILE="${OUTPUT_PATH}/network.net.xml"

export SUMO_HOME="/usr/share/sumo"

    # --junctions.corner-detail 5 \
    # --junctions.limit-turn-speed 8 \
    # --junctions.join-dist 2.0 \

# use sumo netconvert tool to convert the osm file to a sumo network file
netconvert --osm-files $SOURCE_FILE -o $TARGET_FILE \
    --ramps.guess \
    --junctions.join \
    --junctions.join-output "./junction_output.xml" \
    --junctions.join-dist 5 \
    --tls.guess-signals \
    --tls.discard-simple \
    --tls.join \
    --tls.default-type actuated \
    -t $SUMO_HOME/data/typemap/osmNetconvert.typ.xml \
    --remove-edges.by-vclass rail,rail_fast,bicycle,pedestrian\
    --remove-edges.isolated \
    --output.street-names true \
    --output.original-names true 