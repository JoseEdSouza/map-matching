#!/bin/sh

mkdir -p ./networks/xml
mkdir -p ./networks/pbf

chmod -R a+rw ./networks/xml
chmod -R a+rw ./networks/pbf

XML_FILEPATH="./networks/xml/newson_krumm_reconstructed.osm.xml"
PBF_FILEPATH="./networks/pbf/newson_krumm_reconstructed.osm.pbf"

# Executar Osmosis via Docker como se fosse binário
# docker run --rm -it \
#     -v "$(pwd)":/data \
#     andygol/osmosis:0.49.2 \
#     --read-pbf /data/networks/pbf/$PBF_FILEPATH \
#     --write-xml /data/networks/xml/$XML_FILEPATH \

docker run --rm -it \
    -v "$(pwd)":/data \
    andygol/osmosis:0.49.2 \
    --read-xml file="/data/$XML_FILEPATH" \
    --write-pbf file="/data/$PBF_FILEPATH"