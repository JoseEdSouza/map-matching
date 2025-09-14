#!/bin/sh

mkdir -p ./networks/xml
mkdir -p ./networks/pbf

chmod -R a+rw ./networks/xml
chmod -R a+rw ./networks/pbf

# Executar Osmosis via Docker como se fosse binário
docker run --rm -it \
    -v "$(pwd)":/data \
    andygol/osmosis:0.49.2 \
    --read-pbf /data/networks/pbf/illinois-250905.osm.pbf \
    --write-xml /data/networks/xml/illinois-250905.osm.xml \


# docker run --rm -it \
#     -v "$(pwd)":/data \
#     andygol/osmosis:0.49.2 \
#     --read-xml file="/data/networks/xml/newson_krumm_reconstructed_2.osm.xml" \
#     --write-pbf file="/data/networks/pbf/newson_krumm_reconstructed_2.osm.pbf"