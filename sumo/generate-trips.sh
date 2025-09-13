NETWORK_FILE="./sumo/simulations/ohare-chicago/ohare_network.net.xml"
OUTPUT_FILE_TRIPS="./sumo/simulations/ohare-chicago/ohare_trips.trips.xml"
OUTPUT_FILE_ROUTES="./sumo/simulations/ohare-chicago/ohare_routes.rou.xml"

python3 $SUMO_HOME/tools/randomTrips.py \
    -n $NETWORK_FILE  \
    -o $OUTPUT_FILE_TRIPS \
    -r $OUTPUT_FILE_ROUTES \
    --min-distance 500 \
    --binomial 500 \
    --begin 0 \
    --end 3600 \
    --period 2 \
    --seed 42 \
    # --binomial 500 \