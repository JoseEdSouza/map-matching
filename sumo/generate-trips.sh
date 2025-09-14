OUTPUT_PATH="./sumo/simulations/ohare-chicago"
NETWORK_FILE="./sumo/simulations/ohare-chicago/ohare.net.xml"

# GET THE FILENAME
BASENAME=$(basename "$NETWORK_FILE" .net.xml)

OUTPUT_FILE_TRIPS="${OUTPUT_PATH}/${BASENAME}.trips.xml"

OUTPUT_FILE_TRIPS="${OUTPUT_PATH}/${BASENAME}.trips.xml"
OUTPUT_FILE_ROUTES="${OUTPUT_PATH}/${BASENAME}.rou.xml"

export SUMO_HOME="/usr/share/sumo"

python3 $SUMO_HOME/tools/randomTrips.py \
    -n $NETWORK_FILE  \
    -o $OUTPUT_FILE_TRIPS \
    -r $OUTPUT_FILE_ROUTES \
    --min-distance 500 \
    --begin 0 \
    --end 3600 \
    --period 2 \
    --seed 42 \
    # --binomial 500 \