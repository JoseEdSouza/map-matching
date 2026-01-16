# Map Matching Benchmarking Framework

This project is an automated evaluation framework designed to test and compare different **Map Matching** solutions (such as OSRM, GraphHopper, Barefoot, and Graphium) under controlled conditions, using simulated GPS data and real-time performance metrics.

## 🚀 Project Walkthrough

The framework orchestrates the complete lifecycle of a benchmarking experiment, from data preparation to infrastructure metrics collection.

### Simplified Architecture

1. **Orchestrator (`run_benchmarking.py`)**: The entry point that manages configurations, loads datasets, and iterates over combinations of vehicles, sampling rates, and algorithms.
2. **Service Manager (`bench/`)**: Controls the startup and shutdown of Docker containers for each matcher in an isolated manner.
3. **Monitoring Stack**: Uses **Prometheus** and **cAdvisor** to collect CPU, RAM, and Network metrics from running containers.
4. **Stream Emitter (`GPSStreamEmitter`)**: Simulates the transmission of GPS points in "real-time" to the matchers, allowing the evaluation of *end-to-end* latency.

For in-depth technical details, consult the [ARCHITECTURE.md](file:///home/jose_edsouza/Documentos/Faculdade/TCC/repo/map-matching/docs/ARCHITECTURE.md) file.

---

## 🛠 Prerequisites and Setup

### Required Tools

- **Python 3.13.5**
- **[uv](https://github.com/astral-sh/uv)**: Extremely fast Python project and package manager.
- **Docker & Docker Compose**: To run map matching and monitoring services.
- **Make**: For setup task automation.
- **SUMO (Simulation of Urban MObility)** (Optional): Only if you wish to generate new synthetic trajectories.

### Installation

1. Clone the repository:

    ```bash
    git clone https://github.com/JoseEdSouza/map-matching.git
    cd map-matching
    ```

2. Install dependencies with `uv`:

    ```bash
    # Creates the virtual environment and syncs dependencies defined in pyproject.toml
    uv sync
    ```

3. Prepare Matchers (Map Import):
    Each matcher needs to process OpenStreetMap (OSM) data before running. Use the `Makefile` to simplify this:

    ```bash
    # For GraphHopper
    make graphhopper-setup

    # For OSRM
    make osrm-setup

    # For Barefoot
    make barefoot-setup

    # For Graphium
    make graphium-setup
    ```

---

## 🚦 Running the Benchmark

The main script `run_benchmarking.py` handles all automation. Ensure you activate the `uv` virtual environment or run via `uv run`.

```bash
uv run run_benchmarking.py
```

What happens during execution:

- The framework brings up the metrics stack (Prometheus/cAdvisor).
- For each test configuration:
    1. Starts the Matcher container (e.g., OSRM).
    2. Simulates the GPS trajectory stream.
    3. Collects matching results and latency.
    4. Stops the Matcher container.
    5. Extracts resource consumption metrics from Prometheus.
- Finally, it generates consolidated reports in the `metrics/` folder.

---

## 🚗 Traffic Simulation (SUMO)

The `sumo/` directory contains scripts to generate synthetic traffic scenarios and extract GPS trajectories with controlled noise ("Ground Truth" vs "Noisy GPS").

To run a new simulation:

1. Access the directory:

    ```bash
    cd sumo
    ```

2. Run the simulation script (ensure SUMO is installed and configured in PATH):

    ```bash
    # Example: runs the simulation and saves data in Parquet format
    uv run run_simulation_save_to_parquet.py
    ```

Auxiliary scripts like `setup_std_simulation.sh` can be used to prepare the road network and generate random trips before the main execution.

---

## 📊 Results Analysis

Raw benchmark results can be analyzed using the `result_analysis.ipynb` notebook. It generates comparative tables and figures saved in `results/figures/`.

### Examples of Generated Figures

- **Accuracy by Sampling Rate**: Compares the F1-score of each tool (RQ1).
- **Processing Latency**: Latency distribution (p95, p99) to evaluate temporal efficiency (RQ2).
- **Resource Consumption**: Average CPU and Memory usage during experiments (RQ3).
- **Throughput**: Processing capacity in points per second (RQ4).

Consult the notebook for the complete statistical analysis.

---

## 📂 Directory Structure

- `bench/`: Python modules for container and Prometheus control.
- `docs/`: Additional diagrams and documentation.
- `networks/`: OSM, PBF, and GraphML road network files.
- `tools/`: Configuration scripts specific to each tool (OSRM, GH, etc.).
- `mmlib/`: Base library with common interfaces and types for matchers.
- `sumo/`: Simulation scripts and synthetic dataset generation.
