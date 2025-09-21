#!/bin/bash

SIMULATION_PATH="$(pwd)/sumo/simulations/ohare-chicago/simulation.sumocfg"

export SUMO_HOME="/usr/share/sumo"

sumo -c $SIMULATION_PATH