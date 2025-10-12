set -e

echo "Warning: This script is a convienience script for setting up a standard simulation environment. It may not be suitable for all use cases."
echo "You need to set all files and paths correctly before running this script in the other scripts."
echo "Please review the scripts in the sumo/ directory before running this script."

echo "\n\nSetting up standard simulation environment..."
echo "--------------------------------"
echo "Converting network..."
sudo sh $(pwd)/sumo/convert_network.sh
echo "--------------------------------"
echo "Generating grid TAZ..."
sudo sh $(pwd)/sumo/generate_grid_taz.sh
echo "--------------------------------"
echo "Generating random trips..."
sudo sh $(pwd)/sumo/generate_random_trips.sh


