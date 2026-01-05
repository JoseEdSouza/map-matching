#!/bin/sh

GRAPH_NAME="network"
GRAPH_VERSION="1"

echo "Starting Graphium Neo4j server..."

docker compose up -d graphium-neo4j

echo "Waiting for Graphium Neo4j server to be ready..."

for i in {1..30}; do
  STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:7474/graphium/api/health)
  if [ "$STATUS_CODE" -eq 200 ]; then
    echo "Graphium Neo4j server is ready."
    break
  else
    echo .
    sleep 1
  fi
done

sleep 10

echo "Importing OSM network data into Graphium Neo4j server..."

docker exec -it mm-graphium-neo4j java -jar /osm2graphium.one-jar.jar \
  -i /networks/network.osm.pbf \
  -o / \
  -n $GRAPH_NAME \
  -fd false \
  -v $GRAPH_VERSION \
  -q 20000 \
  -t 20 \
  -u "http://localhost:7474/graphium/api/segments/graphs/$GRAPH_NAME/versions/$GRAPH_VERSION?overrideIfExists=true"

echo "."

echo "Setting the imported graph version to ACTIVE..."

curl -X PUT "http://localhost:7474/graphium/api/metadata/graphs/$GRAPH_NAME/versions/$GRAPH_VERSION/state/ACTIVE"

echo "\nNetwork setup completed."