#!/bin/sh


NETWORK_PATH="./networks/xml/ohare.osm.xml"

FILENAME=$(basename "$NETWORK_PATH" .osm.xml)
OUTPUT_FILE="./networks/filtered/${FILENAME}-filtered.osm.xml"


mkdir -p ./networks/xml
mkdir -p ./networks/filtered

chmod -R a+rw ./networks/xml
chmod -R a+rw ./networks/filtered

echo "Filtering network data from $NETWORK_PATH to $OUTPUT_FILE"

docker run --rm -it \
    -v "$(pwd)":/data \
    phdax/osmtools:latest \
    osmfilter /data/${NETWORK_PATH} \
    --keep="highway=* building=*" \
    -o=/data/${OUTPUT_FILE} \
