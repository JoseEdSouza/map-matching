.PHONY: import-map run list import-and-run

run:
	@echo "Running the application..."
	@docker compose up graphhopper

stop:
	@echo "Stopping the application..."
	@docker compose stop graphhopper

import-map:
	@echo "Importing map data..."
	@docker compose run --rm import-map

import-and-run:
	@echo "Importing map data and starting the application..."
	@make import-map
	@make run

list:
	@echo "Available targets:"
	@echo "-------------------------------------------------"
	@echo "| Target           | Description                |"
	@echo "-------------------------------------------------"
	@echo "| run              | Start the GraphHopper app  |"
	@echo "| import-map       | Import map data from OSM   |"
	@echo "| import-and-run   | Import map and start app   |"
	@echo "| list             | Show this help message     |"
	@echo "| stop             | Stop the GraphHopper app   |"
	@echo "-------------------------------------------------"