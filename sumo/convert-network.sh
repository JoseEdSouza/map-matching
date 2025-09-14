#!/bin/bash


SOURCE_FILE="./networks/xml/ohare.osm.xml"
OUTPUT_PATH="./sumo/simulations/ohare-chicago"


BASENAME=$(basename "$SOURCE_FILE" .osm.xml)
TARGET_FILE="${OUTPUT_PATH}/${BASENAME}.net.xml"

export SUMO_HOME="/usr/share/sumo"

# use sumo netconvert tool to convert the osm file to a sumo network file
netconvert --osm-files $SOURCE_FILE -o $TARGET_FILE 