## help: list and explain all commands
.PHONY: help
help:
	@echo "+----------------------+----------------------------------------+"
	@echo "| Target               | Description                            |"
	@echo "+----------------------+----------------------------------------+"
	@sed -n 's/^## //p' $(MAKEFILE_LIST) \
	| awk -F ':' '{ \
		printf "| %-20s | %-38s |\n", $$1, $$2 \
	}'
	@echo "+----------------------+----------------------------------------+"

## stop: stop all running containers
.PHONY: stop
stop:
	@echo "Stopping the application..."
	@docker compose stop

## graphhopper-setup: import map data for GraphHopper
.PHONY: graphhopper-setup
graphhopper-setup:
	@echo "Importing map data..."
	@sudo sh ./tools/graphhopper/setup.sh

## graphhopper-run: start the GraphHopper application
.PHONY: graphhopper-run
graphhopper-run:
	@echo "Running the application..."
	@docker compose up graphhopper

## osrm-setup: import map data for OSRM
.PHONY: osrm-setup
osrm-setup:
	@echo "Importing map data for OSRM..."
	@sudo sh ./tools/osrm/setup.sh

## osrm-run: start the OSRM application
.PHONY: osrm-run
osrm-run:
	@echo "Running OSRM..."
	@docker compose up osrm osrm_frontend

## barefoot-setup: import map data for Barefoot
.PHONY: barefoot-setup
barefoot-setup:
	@echo "Importing map data for Barefoot..."
	@sudo sh ./tools/barefoot/setup.sh

## barefoot-run: start the Barefoot application
.PHONY: barefoot-run
barefoot-run:
	@echo "Running Barefoot..."
	@docker compose up barefoot-map barefoot-tracker barefoot-matcher

## graphium-setup: import map data for Graphium
.PHONY: graphium-setup
graphium-setup:
	@echo "Importing map data for Graphium..."
	@sudo sh ./tools/graphium/setup.sh

## graphium-run: start the Graphium application
.PHONY: graphium-run
graphium-run:
	@echo "Running Graphium..."
	@docker compose up graphium-neo4j