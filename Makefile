.PHONY: list
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
	@echo "| barefoot-run           | Start the Barefoot app           |"
	@echo "|-----------------------------------------------------------|"
	@echo "| list                   | Show this help message           |"
	@echo "| stop                   | Stop the current application     |"
	@echo "-------------------------------------------------------------"

.PHONY: graphhopper-run
graphhopper-run:
	@echo "Running the application..."
	@docker compose up graphhopper

.PHONY: stop
stop:
	@echo "Stopping the application..."
	@docker compose stop

.PHONY: graphhopper-setup
graphhopper-setup:
	@echo "Importing map data..."
	@sudo sh ./tools/graphhopper/setup.sh

.PHONY: osrm-run
osrm-run:
	@echo "Running OSRM..."
	@docker compose up osrm osrm_frontend

.PHONY: osrm-setup
osrm-setup:
	@echo "Importing map data for OSRM..."
	@sudo sh ./tools/osrm/setup.sh

.PHONY: barefoot-run
barefoot-run:
	@echo "Running Barefoot..."
	@docker compose up barefoot-map-server barefoot-tracker-server barefoot-matcher-server