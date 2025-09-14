
# https://github.com/IsraelHikingMap/graphhopper-docker-image-push/blob/main/Dockerfile
# https://github.com/IsraelHikingMap/graphhopper-docker-image-push

#   import-map:
#     image: israelhikingmap/graphhopper:latest
#     container_name: import_osm
#     environment:
#       - JAVA_OPTS=-Xmx8g -Xms8g
#       - FILE=/data/newson_krumm_reconstructed_2.osm.pbf
#       - ACTION=import
#       - CONFIG=/config/config.yaml
#     volumes:
#       - ./tools/graphhopper/volumes/graphhopper_data:/data
#       - ./osm/pbf:/osm
#       - ./tools/graphhopper/config:/config
#     entrypoint:  ["./graphhopper.sh", "-c", "/config/config.yaml"]

ROAD_NETWORK_DIR=osm/pbf
FILENAME=newson_krumm_reconstructed.osm.pbf

docker run --rm \
    -e JAVA_OPTS="-Xmx8g -Xms8g" \
    -e FILE="/road-network/$FILENAME" \
    -e ACTION="import" \
    -e CONFIG="/config/config.yaml" \
    -v "$(pwd)/$ROAD_NETWORK_DIR:/road-network" \
    -v "$(pwd)/tools/graphhopper/config:/config" \
    -v "$(pwd)/tools/graphhopper/volumes/graphhopper_data:/data" \
    --entrypoint ./graphhopper.sh \
    israelhikingmap/graphhopper:latest \
    -c /config/config.yaml
