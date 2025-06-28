#!/bin/sh


mkdir -p ./osm/pbf

chmod -R a+rw ./osm/pbf

OSM_FILENAME="newson_krumm_reconstructed_2"
OSM_FILE="${OSM_FILENAME}.osm.pbf"
ORSM_DATA_DIR="${PWD}/osrm_data"

set -e # Exit on error

echo "Extracting OSM data to orsm format..."
docker run --rm -t \
    -v "${ORSM_DATA_DIR}:/data" \
     ghcr.io/project-osrm/osrm-backend \
     osrm-extract -p /opt/car.lua /data/${OSM_FILE}|| echo "osrm-extract failed"

sleep 3

echo "Partitioning OSM data for routing..."
docker run --rm -t \
    -v "${ORSM_DATA_DIR}:/data" \
    ghcr.io/project-osrm/osrm-backend osrm-partition /data/${OSM_FILENAME}.osrm || echo "osrm-partition failed"

sleep 3

echo "Customizing OSM data for routing..."
docker run --rm -t \
    -v "${ORSM_DATA_DIR}:/data" \
     ghcr.io/project-osrm/osrm-backend osrm-customize /data/${OSM_FILENAME}.osrm || echo "osrm-customize failed"

