#!/bin/sh

mkdir -p ./osm/xml

chmod -R a+rw ./osm/xml

# Executar Osmosis via Docker como se fosse binário
docker run --rm -it \
    -v "$(pwd)":/data \
    andygol/osmosis:0.49.2 \
    --read-pbf /data/osm/pbf/washington-latest.osm.pbf \
    --write-xml /data/osm/xml/washington-latest.osm.xml \
