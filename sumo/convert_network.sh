#!/bin/bash

set -e


SOURCE_FILE="./networks/filtered/ohare-filtered.osm.xml"
OUTPUT_PATH="./sumo/simulations/ohare-chicago-junctionless"

chmod -R a+rw "$SOURCE_FILE"

TARGET_FILE="${OUTPUT_PATH}/network.net.xml"

export SUMO_HOME="/usr/share/sumo"


    # --no-turnarounds \
    # --no-turnarounds.except-deadend \
    # --no-turnarounds.except-turnlane \
    # --no-turnarounds.fringe \

    # --keep-edges.postload \
    # --remove-edges.explicit edgeid,edge2id \

# :cluster_2610439065_263785875_311482791_311482827
# :cluster_310333647_310333648_4_0


# --junctions.join-exclude 2610439065,263785875,311482791,311482827,310333647,310333648 \

# use sumo netconvert tool to convert the osm file to a sumo network file
netconvert --osm-files $SOURCE_FILE -o $TARGET_FILE \
    --ramps.guess \
    --junctions.join \
    --junctions.join-dist 5 \
    --junctions.join-exclude 2610439065,263785875,311482791,311482827,310333647,310333648 \
    --tls.guess-signals \
    --tls.discard-simple \
    --tls.join \
    --tls.default-type actuated \
    -t $SUMO_HOME/data/typemap/osmNetconvert.typ.xml \
    --remove-edges.by-vclass rail,rail_fast,bicycle,pedestrian \
    --remove-edges.isolated \
    --output.street-names true \
    --output.original-names true 