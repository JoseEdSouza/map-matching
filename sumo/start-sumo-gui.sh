#!/bin/bash

SIMULATION_PATH="$(pwd)/sumo/simulations/ohare-chicago/simulation.sumocfg"

export SUMO_HOME="/usr/share/sumo"

# check if there is a nvidia gpu
if lspci | grep -i nvidia; then
    echo "NVIDIA GPU detected. Setting up environment for GPU offloading."
    export __NV_PRIME_RENDER_OFFLOAD=1
    export __GLX_VENDOR_LIBRARY_NAME=nvidia
else
    echo "No NVIDIA GPU detected. Running with default settings."
fi


sumo-gui $SIMULATION_PATH