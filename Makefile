.PHONY: graphhopper-run graphhopper-setup osrm-run osrm-setup list stop

graphhopper-run:
	@echo "Running the application..."
	@docker compose up graphhopper

stop:
	@echo "Stopping the application..."
	@docker compose stop

graphhopper-setup:
	@echo "Importing map data..."
	@docker compose run --rm import-map

osrm-run:
	@echo "Running OSRM..."
	@docker compose up osrm

osrm-setup:
	@echo "Importing map data for OSRM..."
	@sudo sh osrm.sh

list:
	@echo "Available targets:"
	@echo "-------------------------------------------------------------"
	@echo "| Target                 | Description                      |"
	@echo "|-----------------------------------------------------------|"
	@echo "| graphhopper-run        | Start the GraphHopper app        |"
	@echo "| graphhopper-setup      | Import map data for GraphHopper  |"
	@echo "|-----------------------------------------------------------|"
	@echo "| osrm-run               | Start the OSRM app               |"
	@echo "| osrm-setup             | Import map data for OSRM         |"
	@echo "|-----------------------------------------------------------|"
	@echo "| list                   | Show this help message           |"
	@echo "| stop                   | Stop the current application     |"
	@echo "-------------------------------------------------------------"