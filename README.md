# Online Map Matching Benchmark

A systematic, reproducible benchmark for **open-source online map matching** tools. It compares natively online tools (Barefoot, GraphiumMM) with natively offline ones (OSRM, GraphHopper) that are adapted to incremental execution through client-side micro-batching. The tools are evaluated on accuracy, latency, resource usage and throughput, using a synthetic dataset with exact ground truth.

This repository contains the benchmark harness, the synthetic dataset and the analysis behind the bachelor's thesis (B.Sc. in Software Engineering, UFC) below.

## 📄 Publication

> SOUZA, José Vinícius Evangelista Dias de. **Benchmark comparativo de ferramentas de código aberto para map matching online**. 2026. 109 f. Trabalho de Conclusão de Curso (Graduação em Engenharia de Software) - Campus de Quixadá, Universidade Federal do Ceará, Quixadá, 2026.

Full text (Portuguese): [UFC institutional repository](http://repositorio.ufc.br/handle/riufc/85759). Advisor: Prof. Dr. Regis Pires Magalhães. Co-advisor: Prof. Dr. José Antônio Fernandes de Macêdo.

```bibtex
@mastersthesis{souza2026benchmark,
  author  = {Souza, José Vinícius Evangelista Dias de},
  title   = {Benchmark comparativo de ferramentas de código aberto para map matching online},
  school  = {Universidade Federal do Ceará},
  address = {Quixadá},
  year    = {2026},
  pages   = {109},
  type    = {Trabalho de Conclusão de Curso (Graduação em Engenharia de Software)},
  url     = {http://repositorio.ufc.br/handle/riufc/85759}
}
```

The synthetic ground-truth dataset is also presented in the poster [A Synthetic Ground-Truth Dataset for Online Map Matching](docs/publications/poster-eniac-2026.pdf) (ENIAC 2026).

## ✨ Contributions

1. **Synthetic dataset with exact ground truth**: 1,759 SUMO-simulated trajectories over the O'Hare (Chicago) road network, with Gaussian GNSS noise (σ = 5 m).
2. **Automated benchmark harness**: container-based orchestration, Prometheus/cAdvisor resource monitoring and automatic retries for failed runs.
3. **[`mmlib`](https://github.com/JoseEdSouza/mmlib)**: a client library that gives every tool a common interface, instruments end-to-end metrics, and adapts offline matchers to online streaming (`BatchesOnlineMatcher`).
4. **Multidimensional comparison** of the four tools on accuracy, latency, resource cost and throughput.

## ❓ Research Questions

| RQ | Dimension | Question |
| --- | --- | --- |
| RQ1 | Matching quality | How do F1-score, error rate and Newson–Krumm error vary with the sampling rate? |
| RQ2 | Temporal efficiency | How does mean processing latency vary with the sampling rate? |
| RQ3 | Computational efficiency | How do CPU and memory cost vary with the sampling rate, for a given quality? |
| RQ4 | Continuous processing | How does throughput (points/s and km/s) vary with the sampling rate? |

---

## 🧰 Evaluated Tools

| Tool | Native paradigm | Interface | Adaptation for the benchmark |
| --- | --- | --- | --- |
| [Barefoot](https://github.com/bmwcarit/barefoot) | Online and offline | ZeroMQ sockets | [Fork](https://github.com/JoseEdSouza/barefoot) that exposes OSM way IDs in the output |
| [GraphiumMM](https://github.com/graphium-project/graphium-neo4j) | Online and offline (Neo4j plugin) | HTTP | Forks of [graphium](https://github.com/JoseEdSouza/graphium) and [graphium-neo4j](https://github.com/JoseEdSouza/graphium-neo4j) that keep OSM way IDs |
| [OSRM](https://github.com/Project-OSRM/osrm-backend) | Offline | HTTP | Lua profile [`car_with_wayids.lua`](tools/osrm/config/car_with_wayids.lua) only |
| [GraphHopper](https://github.com/graphhopper/graphhopper) | Offline | HTTP | [`config.yaml`](tools/graphhopper/config/config.yaml) only |

All changes only expose OSM edge identifiers, which the accuracy metrics need. None of them changes how the matching algorithms behave.

## 🧪 Experimental Setup

| Factor | Levels |
| --- | --- |
| Workload | 20 trajectories, stratified by length quartile (5 per quartile) |
| Sampling rate (`sr`) | 1 s, 5 s, 10 s, 20 s |
| Batch size (`bs`) | 5, 10, 30 points (all tools except Barefoot) |
| Speed factor (`sf`) | 30 (points are emitted with a delay of Δt / sf) |
| Repetitions | 3 per batched configuration |

This gives 800 planned runs. 790 completed successfully (98.75%).

## 📈 Key Findings

| Tool | F1 (1 s → 20 s) | Mean latency (1 s → 20 s) | Mean memory | Throughput |
| --- | --- | --- | --- | --- |
| **Barefoot** | 0.962 → 0.976 | 35 → 622 ms | 125–308 MB | ~0.13 km/s |
| **OSRM** | 0.946 → 0.819 | 365 → 4,138 ms | 3–11 MB | ~0.19 km/s |
| **GraphiumMM** | 0.931 → 0.957 | 269 → 8,998 ms | ~1.44 GB | ~0.08 km/s |
| **GraphHopper** | 0.786 → 0.772 | 316 → 4,195 ms | ~320 MB | ~0.09 km/s |

No tool wins on every dimension. Practical guidelines:

- **Barefoot**: best accuracy, robust to sparse sampling, and the lowest latency. It is harder to deploy, because it is distributed and uses ZeroMQ instead of HTTP.
- **OSRM**: lowest CPU and memory use and highest throughput, with a simple HTTP integration. Its accuracy drops at sparse sampling rates, so it fits dense data on constrained infrastructure.
- **GraphiumMM**: competitive accuracy, but it has the highest latency and memory cost (Neo4j and JVM overhead) and needs a larger first batch to start well (cold start). It is a good fit when you already use a graph database.
- **GraphHopper**: not recommended as a first choice. In this setup it did not lead on any dimension.

---

## 🚀 Architecture

1. **Orchestrator ([`run_benchmarking.py`](run_benchmarking.py))**: entry point. It loads the configuration and dataset and iterates over every tool × trajectory × sampling rate × batch size combination.
2. **Service manager ([`bench/`](bench/))**: recreates each matcher's Docker container per experiment, labelled with the experiment ID.
3. **Monitoring stack**: Prometheus and cAdvisor collect container CPU, memory and network usage. After each run, `bench/prom_export.py` queries these metrics by experiment ID.
4. **Stream emitter (`GPSStreamEmitter`)**: replays GNSS points in timestamp order, speeded up by `sf`, through `mmlib` matchers that record end-to-end latency and throughput.

For more technical detail, see [ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 🛠 Prerequisites and Setup

### Required tools

- **Python 3.13.5**
- **[uv](https://github.com/astral-sh/uv)**: Python project and package manager
- **Docker and Docker Compose**: run the matchers and the monitoring stack
- **Make**: setup automation
- **SUMO** (optional): only needed to generate new synthetic trajectories

### Installation

1. Clone the repository:

    ```bash
    git clone https://github.com/JoseEdSouza/map-matching.git
    cd map-matching
    ```

2. Install dependencies, including `mmlib` from Git:

    ```bash
    uv sync
    ```

3. Import the map for each matcher. Each one preprocesses the OSM data:

    ```bash
    make graphhopper-setup
    make osrm-setup
    make barefoot-setup
    make graphium-setup
    ```

    Run `make help` to list every target.

---

## 🚦 Running the Benchmark

```bash
uv run run_benchmarking.py
```

During execution:

- The monitoring stack (Prometheus and cAdvisor) starts.
- For each configuration, the harness:
    1. Starts the matcher container.
    2. Streams the GNSS trajectory to the matcher.
    3. Collects the matching results and end-to-end metrics.
    4. Queries Prometheus for resource metrics.
    5. Stops the container. A failed run is retried up to 3 times.
- Finally, it writes the consolidated reports to `metrics/` and `results/`.

---

## 🚗 Synthetic Dataset (SUMO)

The pipeline in [`sumo/`](sumo/) builds the ground-truth dataset:

1. Extract the O'Hare drive network with OSMnx, filter it with osmfilter and convert it with `netconvert`, keeping OSM edge IDs traceable.
2. Generate trips with `randomTrips.py` (seed 42, 1 h, minimum trip length 500 m) and simulate them with a 0.5 s step, collecting positions through TraCI.
3. Map SUMO internal edges back to OSM edges and add 2D Gaussian noise (μ = 0, σ = 5 m).
4. Save the results as Parquet: [`dataset/ground_truth.parquet`](dataset/) and [`dataset/gps_noisy.parquet`](dataset/).

To regenerate the dataset (SUMO must be on your `PATH`):

```bash
cd sumo
uv run run_simulation_save_to_parquet.py
```

Helper scripts such as `setup_std_simulation.sh` prepare the network and the random trips.

---

## 📊 Results Analysis

[`result_analysis.ipynb`](result_analysis.ipynb) builds the comparison tables and the figures in [`results/figures/`](results/figures/). File names are prefixed by research question: `qp1_*` for quality, `qp2_*` for latency, `qp3_*` for resources and `qp4_*` for throughput. The aggregated CSVs are in [`results/`](results/).

---

## 📂 Directory Structure

- `bench/`: Docker Compose and Prometheus control
- `dataset/`: synthetic dataset (ground truth, noisy GNSS points, O'Hare network)
- `demo/`: example requests for each matcher
- `docs/`: architecture, diagrams and publications
- `eda/`: exploratory analysis of public trajectory datasets
- `networks/`: OSM, PBF, GraphML and GeoJSON road networks
- `results/`: aggregated metrics and figures
- `scripts/`: network conversion and plotting utilities
- `sumo/`: traffic simulation and dataset generation
- `tools/`: per-matcher configuration (OSRM, GraphHopper, Barefoot, Graphium, Prometheus)

## 🔁 Reproducibility

The thesis results were produced with these exact versions:

| Artifact | Repository | Commit |
| --- | --- | --- |
| Benchmark harness and dataset | [JoseEdSouza/map-matching](https://github.com/JoseEdSouza/map-matching/tree/45a3ebf) | `45a3ebf` |
| mmlib | [JoseEdSouza/mmlib](https://github.com/JoseEdSouza/mmlib) | `f57a132` |
| Barefoot (adapted) | [JoseEdSouza/barefoot](https://github.com/JoseEdSouza/barefoot) | `53eec69` |
| Graphium (import) | [JoseEdSouza/graphium](https://github.com/JoseEdSouza/graphium) | `54d1a86` |
| GraphiumMM (adapted) | [JoseEdSouza/graphium-neo4j](https://github.com/JoseEdSouza/graphium-neo4j) | `b465f6a` |
| OSRM | [Project-OSRM/osrm-backend](https://github.com/Project-OSRM/osrm-backend) | `c98537b` |
| GraphHopper | [graphhopper/graphhopper](https://github.com/graphhopper/graphhopper) | `88335ad` |
| GraphHopper (Docker) | [IsraelHikingMap/graphhopper-docker](https://github.com/IsraelHikingMap/graphhopper-docker) | `c3d6b8d` |

Test machine: Intel Core i7-12700H, 32 GB DDR5, NVMe SSD, Kubuntu 24.04.3 LTS (kernel 6.8). Containers had no resource limits.
