FCD_FILEPATH="./sumo/simulations/ohare-chicago/output/fcd.xml"


BASE_PATH=$(dirname $FCD_FILEPATH)
GPX_CLEAN_OUTPUT=$BASE_PATH/$(basename $FCD_FILEPATH .xml).gpx
GPSDAT_CLEAN_OUTPUT=$BASE_PATH/$(basename $FCD_FILEPATH .xml).gpsdat.csv

GPX_OUTPUT=$BASE_PATH/$(basename $FCD_FILEPATH .xml)_distorted.gpx
GPSDAT_OUTPUT=$BASE_PATH/$(basename $FCD_FILEPATH .xml)_distorted.gpsdat.csv

python3 $SUMO_HOME/tools/traceExporter.py \
    --fcd-input $FCD_FILEPATH \
    --gpsdat-output $GPSDAT_CLEAN_OUTPUT \
    --gpx-output $GPX_CLEAN_OUTPUT \
    --delta-t 1

python3 $SUMO_HOME/tools/traceExporter.py \
    --fcd-input $FCD_FILEPATH \
    --gpsdat-output $GPSDAT_OUTPUT \
    --gpx-output $GPX_OUTPUT \
    --delta-t 1 \
    --gps-blur 5 \
    --seed 42