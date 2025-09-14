#!/bin/sh

# https://github.com/Project-OSRM/osrm-backend

NETWORK_DIR=osm/pbf
OSM_FILENAME="newson_krumm_reconstructed"


OSM_FILE="${OSM_FILENAME}.osm.pbf"
ORSM_DATA_DIR="tools/osrm/volumes/osrm_data"


sudo mkdir -p ${NETWORK_DIR}
sudo chmod -R a+rw ${NETWORK_DIR}

sudo mkdir -p ${ORSM_DATA_DIR}
sudo cp ${NETWORK_DIR}/${OSM_FILE} ${ORSM_DATA_DIR}/

set -e # Exit on error

echo "Extracting OSM data to orsm format..."
docker run --rm -t \
    -v "$(pwd)/${ORSM_DATA_DIR}:/data" \
     ghcr.io/project-osrm/osrm-backend \
     osrm-extract -p /opt/car.lua /data/${OSM_FILE} || echo "osrm-extract failed"

sleep 3

echo "Partitioning OSM data for routing..."
docker run --rm -t \
    -v "$(pwd)/${ORSM_DATA_DIR}:/data" \
    ghcr.io/project-osrm/osrm-backend osrm-partition /data/${OSM_FILENAME}.osrm || echo "osrm-partition failed"

sleep 3

echo "Customizing OSM data for routing..."
docker run --rm -t \
    -v "$(pwd)/${ORSM_DATA_DIR}:/data" \
     ghcr.io/project-osrm/osrm-backend osrm-customize /data/${OSM_FILENAME}.osrm || echo "osrm-customize failed"

echo "OSRM data setup completed."
sudo rm -rf $(pwd)/${ORSM_DATA_DIR}/${OSM_FILE}