SOURCE_FILE="./ohare-chicago/data/ohare_network.osm.xml"
TARGET_FILE="./sumo/simulations/ohare-chicago/ohare_network.net.xml"


# use sumo netconvert tool to convert the osm file to a sumo network file
netconvert --osm-files $SOURCE_FILE -o $TARGET_FILE 