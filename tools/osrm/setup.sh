#!/bin/sh

NETWORK_DIR=networks/pbf
OSM_FILE="ohare-filtered.osm.pbf"
OSRM_DATA_DIR="tools/osrm/volumes/osrm_data"

# NOVO: Diretório para o profile customizado
PROFILE_DIR="tools/osrm/config"
CUSTOM_PROFILE="${PROFILE_DIR}/car_with_wayids.lua"

rm -rf ./tools/osrm/volumes/osrm_data/*

sudo mkdir -p ${NETWORK_DIR}
sudo chmod -R a+rw ${NETWORK_DIR}

sudo mkdir -p ${OSRM_DATA_DIR}
sudo mkdir -p ${PROFILE_DIR}  # Cria diretório para profiles
sudo chmod -R a+rw ${PROFILE_DIR}

sudo cp ${NETWORK_DIR}/${OSM_FILE} ${OSRM_DATA_DIR}/network.osm.pbf

set -e

echo "Extracting OSM data with custom profile..."
docker run --rm -t \
    -v "$(pwd)/${OSRM_DATA_DIR}:/data" \
    -v "$(pwd)/${PROFILE_DIR}:/profiles" \
    ghcr.io/project-osrm/osrm-backend \
    osrm-extract -p /profiles/car_with_wayids.lua /data/network.osm.pbf

sleep 3

echo "Partitioning OSM data..."
docker run --rm -t \
    -v "$(pwd)/${OSRM_DATA_DIR}:/data" \
    ghcr.io/project-osrm/osrm-backend osrm-partition /data/network.osrm

sleep 3

echo "Customizing OSM data..."
docker run --rm -t \
    -v "$(pwd)/${OSRM_DATA_DIR}:/data" \
    ghcr.io/project-osrm/osrm-backend osrm-customize /data/network.osrm

echo "OSRM data setup completed with way IDs enabled."
sudo rm -rf $(pwd)/${OSRM_DATA_DIR}/${OSM_FILE}
