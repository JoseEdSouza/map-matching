#!/bin/sh

mkdir -p ./osm/xml
mkdir -p ./osm/pbf

chmod -R a+rw ./osm/xml
chmod -R a+rw ./osm/pbf

# Executar Osmosis via Docker como se fosse binário
# docker run --rm -it \
#     -v "$(pwd)":/data \
#     andygol/osmosis:0.49.2 \
#     --read-pbf /data/osm/pbf/washington-latest.osm.pbf \
#     --write-xml /data/osm/xml/washington-latest.osm.xml \


docker run --rm -it \
    -v "$(pwd)":/data \
    andygol/osmosis:0.49.2 \
    --read-xml file="/data/osm/xml/newson_krumm_reconstructed.osm.xml" \
    --write-pbf file="/data/osm/pbf/newson_krumm_reconstructed.osm.pbf"