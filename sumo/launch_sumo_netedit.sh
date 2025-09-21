#!/bin/bash

NETWORK_FILE="$(pwd)/sumo/simulations/ohare-chicago/ohare-filtered.net.xml"
TAZ_FILE="$(pwd)/sumo/simulations/ohare-chicago/ohare-filtered.taz.add.xml"

chmod -R a+rw "$NETWORK_FILE"
chmod -R a+rw "$TAZ_FILE"

export SUMO_HOME="/usr/share/sumo"

# check if there is a nvidia gpu
if lspci | grep -i nvidia; then
    echo "NVIDIA GPU detected. Setting up environment for GPU offloading."
    export __NV_PRIME_RENDER_OFFLOAD=1
    export __GLX_VENDOR_LIBRARY_NAME=nvidia
else
    echo "No NVIDIA GPU detected. Running with default settings."
fi

netedit -s $NETWORK_FILE -a $TAZ_FILE