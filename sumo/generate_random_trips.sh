OUTPUT_PATH="./sumo/simulations/ohare-chicago-junctionless"
NETWORK_FILE="./sumo/simulations/ohare-chicago-junctionless/network.net.xml"

OUTPUT_FILE_TRIPS="${OUTPUT_PATH}/random_trips.trips.xml"
OUTPUT_FILE_ROUTES="${OUTPUT_PATH}/random_routes.rou.xml"

export SUMO_HOME="/usr/share/sumo"

python3 $SUMO_HOME/tools/randomTrips.py \
    -n $NETWORK_FILE  \
    -o $OUTPUT_FILE_TRIPS \
    -r $OUTPUT_FILE_ROUTES \
    --min-distance 500 \
    --begin 0 \
    --end 3600 \
    --period 2 \
    --binomial 10 \
    --seed 42 