#!/bin/bash

SIMULATION_PATH="$(pwd)/sumo/simulations/ohare-chicago/simulation.sumocfg"
OUTPUT_PATH="$(pwd)/sumo/simulations/ohare-chicago/output"


export SUMO_HOME="/usr/share/sumo"

mkdir -p $OUTPUT_PATH

sumo -c $SIMULATION_PATH \
    --fcd-output $OUTPUT_PATH/fcd_output.xml \
    --fcd-output.geo \
    --tripinfo-output $OUTPUT_PATH/tripinfo.xml