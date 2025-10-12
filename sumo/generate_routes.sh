OUTPUT_PATH="./sumo/simulations/ohare-chicago"
NETWORK_FILE="./sumo/simulations/ohare-chicago/network.net.xml"
TAZ_FILE="./sumo/simulations/ohare-chicago/grid_taz.add.xml"
TRIPS_FILE="./sumo/simulations/ohare-chicago/random_trips.trips.xml"

# GET THE FILENAME
BASENAME=$(basename "$NETWORK_FILE" .net.xml)

OUTPUT_FILE_ROUTES="${OUTPUT_PATH}/${BASENAME}.rou.xml"

export SUMO_HOME="/usr/share/sumo"


python3 $SUMO_HOME/tools/assign/duaIterate.py \
    -n $NETWORK_FILE  \
    -t $TRIPS_FILE \
    -D $TAZ_FILE \
    -R 3600 \
    --clean-alt \
    -z \
    -l 2