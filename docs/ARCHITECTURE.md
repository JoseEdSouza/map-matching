# Map Matching Benchmarking Framework Architecture

This document describes the architecture of the map matching benchmark execution system, as implemented in the `bench` modules and the `ohare_run.py` orchestrator.

## Overview

The system is an automated evaluation framework designed to test different map matching solutions (such as OSRM, GraphHopper, Barefoot, Graphium) under controlled conditions. It orchestrates experiment execution, manages service lifecycles via Docker, simulates real-time GPS data streams, and collects detailed performance metrics (latency, throughput) and resource consumption (CPU, memory, network).

## Core Components

### 1. Orchestrator (`BenchmarkOrchestrator`)

Located in `ohare_run.py`, this is the central component coordinating the entire process.

- **Responsibilities:**
  - Load configurations (`BenchmarkConfig`) and test data (trajectories and road network).
  - Iterate over vehicle, sampling rate, and algorithm (matcher) combinations.
  - Manage global execution flow (setup -> execution -> teardown -> reports).
  - Aggregate results from multiple experiments.

### 2. Experiment Executor (`ExperimentRunner`)

Responsible for the logical execution of a single map matching test.

- **Responsibilities:**
  - Simulate sending GPS points in "real-time" using `GPSStreamEmitter`, respecting the `time_speed_factor`.
  - Interact with the *matcher* interface (which must implement `BaseOnlineMatcher`).
  - Collect end-to-end (E2E) latency metrics for each processed point or batch.

### 3. Service Manager (`bench` package)

Module responsible for container-based execution infrastructure.

- **`bench/start_services.py` (`launch_service`):** A context manager that uses `docker compose` to start matcher-specific containers before an experiment and shut them down immediately after. Injects dynamic configurations (like `DATASET_ID`, `EXPERIMENT_ID`) via environment variables.
- **`bench/compose.py`:** Python wrapper for Docker Compose CLI commands.

### 4. Metrics and Observability System (`bench` package)

Collects system performance data during container execution.

- **`bench/start_metrics.py` (`track_metrics`):** Starts the monitoring stack (Prometheus + cAdvisor) as Docker services.
- **`bench/prom_export.py`:** Queries the Prometheus API after each experiment to extract CPU, memory, and network time series, associating them with the experiment ID.

### 5. Data Layer (`DataLoader` & `OutputManager`)

- **Input:** Reads Parquet files (noisy trajectories and ground truth) and GraphML (road network).
- **Output:** Persists raw and aggregated metrics in CSV and JSON, organized by run.

---

## Architecture Diagrams

### Execution Flow (Sequence Diagram)

The diagram below illustrates the lifecycle of a complete benchmark for a set of vehicles.

```mermaid
%%{init: { 'theme': 'base', 'themeVariables': {
    'primaryColor': '#e3f2fd',
    'primaryTextColor': '#0d47a1',
    'primaryBorderColor': '#1565c0',
    'lineColor': '#1e88e5',
    'secondaryColor': '#bbdefb',
    'tertiaryColor': '#ffffff',
    'edgeLabelBackground': '#e3f2fd'
} } }%%

sequenceDiagram
    autonumber
    
    %% Participants
    participant User as 👤 Researcher
    participant Orch as ⚙️ Benchmark<br/>Orchestrator
    participant Stack as 📊 Metrics Stack<br/>(Prom/cAdvisor)
    participant Runner as 🏃 ExperimentRunner
    participant Docker as 🐳 Docker Compose
    participant Matcher as 🧩 Matcher Container
    participant Out as 📁 OutputManager

    Note over Orch, Runner: Main Framework (Python)
    Note over Stack, Docker: Infrastructure Services
    Note over Matcher: Target Algorithm

    User->>Orch: Start Benchmark (run_all_experiments)
    
    Orch->>Stack: track_metrics() (Start Prometheus)
    activate Stack
    
    rect rgb(240, 248, 255)
    Note right of Orch: Loop: For each Vehicle / Sample Rate / Config
    
        Orch->>Docker: launch_service() (Start Matcher)
        activate Matcher
        Docker-->>Orch: Experiment ID
        
        Orch->>Runner: run_single_experiment()
        activate Runner
        
        Runner->>Runner: GPSStreamEmitter (Simulate Stream)
        
        loop Point Stream
            Runner->>Matcher: Send Point/Batch (Request)
            Matcher-->>Runner: Match Result (Response)
            Runner->>Runner: Record E2E Latency
        end
        
        Runner-->>Orch: Match Results and E2E Metrics
        deactivate Runner

        Orch->>Docker: Stop Service
        deactivate Matcher
        
        Orch->>Stack: export_prometheus_timeseries()
        Stack-->>Orch: CPU/RAM/Net Metrics
        
        Orch->>Out: Save Individual Report
    end
    
    Orch->>Stack: Stop Metrics Stack
    deactivate Stack
    
    Orch->>Out: Save Aggregated Metrics
    Orch-->>User: Execution Finished
```

### Component Architecture (Class Diagram)

This diagram shows the relationship between Python classes and system modules.

```mermaid
%%{init: { 'theme': 'base', 'themeVariables': {
    'primaryColor': '#e3f2fd',
    'primaryTextColor': '#0d47a1',
    'primaryBorderColor': '#1565c0',
    'lineColor': '#1e88e5',
    'secondaryColor': '#bbdefb',
    'tertiaryColor': '#ffffff',
    'edgeLabelBackground': '#e3f2fd',
    'fontFamily': 'arial'
} } }%%

classDiagram
    direction TB

    %% --- Styling ---
    classDef core fill:#e1f5fe,stroke:#0277bd,stroke-width:2px;
    classDef infra fill:#f5f5f5,stroke:#9e9e9e,stroke-width:2px;
    classDef storage fill:#fff9c4,stroke:#fbc02d,stroke-width:2px;
    classDef config fill:#ffffff,stroke:#333,stroke-dasharray: 5 5;

    %% --- Vertical Hierarchy ---

    class BenchmarkOrchestrator {
        +BenchmarkConfig config
        +List~MatcherConfig~ matchers
        +DataLoader data_loader
        +ExperimentRunner runner
        +OutputManager output_mgr
        +run_all_experiments()
        +run_vehicle_matcher_experiment()
    }
    class BenchmarkOrchestrator:::core

    class MatcherConfig {
        +BaseOnlineMatcher matcher
        +String name
        +String services
        +String mode
    }
    class MatcherConfig:::config

    class DataLoader {
        +load_trajectory()
        +prepare_data()
    }
    class DataLoader:::core

    class ExperimentRunner {
        +run_single_experiment()
    }
    class ExperimentRunner:::core

    class GPSStreamEmitter {
        +emit()
    }
    class GPSStreamEmitter:::core

    class BenchModule {
        <<Module>>
        +launch_service()
        +track_metrics()
        +export_metrics()
    }
    class BenchModule:::infra

    class DockerCompose {
        <<External>>
        +up()
        +down()
    }
    class DockerCompose:::infra

    class OutputManager {
        +save_individual_report()
        +save_aggregated_metrics()
    }
    class OutputManager:::storage

    %% --- Relationships (Ordered for verticality) ---
    
    BenchmarkOrchestrator o-- MatcherConfig : "owns"
    BenchmarkOrchestrator --> DataLoader : "loads data"
    
    BenchmarkOrchestrator --> ExperimentRunner : "triggers"
    ExperimentRunner --> GPSStreamEmitter : "generates stream"
    ExperimentRunner ..> MatcherConfig : "consumes"

    BenchmarkOrchestrator --> BenchModule : "controls infra"
    BenchModule ..> DockerCompose : "via subprocess"

    BenchmarkOrchestrator --> OutputManager : "exports"

    %% --- Narrow Notes ---
    note for BenchmarkOrchestrator "Entry point.<br/>Reads configs and<br/>manages flow."
    note for BenchModule "Handles Docker<br/>lifecycle and<br/>metrics collection."
    note for GPSStreamEmitter "Simulates real-time<br/>data sending."
```

### Metrics Data Flow

How metrics are collected from different sources and unified.

```mermaid
%%{init: { 'theme': 'base', 'themeVariables': {
    'primaryColor': '#e3f2fd',
    'primaryTextColor': '#0d47a1',
    'primaryBorderColor': '#1565c0',
    'lineColor': '#1e88e5',
    'secondaryColor': '#bbdefb',
    'tertiaryColor': '#ffffff',
    'edgeLabelBackground': '#e3f2fd',
    'fontFamily': 'arial'
} } }%%

graph TD
    %% --- Styles ---
    classDef app fill:#e1f5fe,stroke:#0277bd,stroke-width:2px;
    classDef infra fill:#f5f5f5,stroke:#9e9e9e,stroke-width:2px;
    classDef result fill:#fff9c4,stroke:#fbc02d,stroke-width:2px;

    %% --- Level 1: Data Collection (Side by Side) ---
    subgraph APP [🐍 Python Application]
        direction TB
        Runner[ExperimentRunner]:::app
        E2E_Metrics[E2E Metrics<br/>Latency/Throughput]:::app
        MatcherResult[Match Result]:::app
        Match_Metrics[Quality Metrics<br/>Accuracy/Errors]:::app
        
        Runner ----> E2E_Metrics
        MatcherResult ----> Match_Metrics
    end

    subgraph INFRA [🐳 Docker Infrastructure]
        direction TB
        Container[Matcher Service]:::infra
        CADVISOR[cAdvisor]:::infra
        PROM[Prometheus]:::infra
        
        Container -- "Resource Usage" ----> CADVISOR
        CADVISOR -- "Scrape" ----> PROM
    end

    %% --- Level 2: System Metrics Extraction ---
    PROM -- "Query Range API" ----> PromExport[bench/prom_export.py]:::app
    PromExport -- "DataFrames" ----> Sys_Metrics[System Metrics<br/>CPU/Mem/Net]:::app

    %% --- Level 3: Aggregation and Join ---
    E2E_Metrics ----> Aggregator{MetricsAggregator}:::app
    Match_Metrics ----> Aggregator
    Sys_Metrics ----> Aggregator

    %% --- Level 4: Output ---
    Aggregator -- "Join by ExperimentID" ----> FinalCSV[(Consolidated CSV Reports)]:::result

    %% Subgraph border adjustment
    style APP fill:none,stroke:#0277bd,stroke-dasharray: 5 5
    style INFRA fill:none,stroke:#9e9e9e,stroke-dasharray: 5 5
```

---

## C4 Modeling

Below is the system architecture using the C4 model (Context, Containers, Components).

### Level 1: Context Diagram

The context diagram situates the Benchmarking System relative to users and external systems.

```mermaid
%%{init: { 'theme': 'base', 'themeVariables': {
    'primaryColor': '#e3f2fd',
    'primaryTextColor': '#0d47a1',
    'primaryBorderColor': '#1565c0',
    'lineColor': '#1e88e5',
    'edgeLabelBackground': '#e3f2fd'
} } }%%
graph TD
    %% C4 Style Definition
    classDef person fill:#08427b,color:white,stroke:#052e56,stroke-width:2px;
    classDef system fill:#1168bd,color:white,stroke:#0b4d8c,stroke-width:2px;
    classDef external fill:#999999,color:white,stroke:#666666,stroke-width:2px;

    %% Nodes
    USER["<b>Researcher / Developer</b><br/>[Person]<br/><br/>Configures and runs<br/>experiments."]:::person
    
    BENCH["<b>Benchmark Framework</b><br/>[Software System]<br/><br/>Orchestrates experiments,<br/>simulates data, collects metrics."]:::system

    DOCKER["<b>Docker Engine</b><br/>[External System]<br/><br/>Manages container<br/>execution."]:::external

    FS["<b>File System</b><br/>[External System]<br/><br/>Stores datasets<br/>and results."]:::external

    %% Relationships with long arrows (----->) for text spacing
    USER -- "Starts experiments" -----> BENCH
    BENCH -- "Manages service<br/>lifecycle" ----> DOCKER
    BENCH -- "Reads data and<br/>writes reports" ----> FS

    %% Lateral layout adjustment
    direction TB
```

### Level 2: Container Diagram

This level details the executable applications and services comprising the system.

```mermaid
%%{init: { 'theme': 'base', 'themeVariables': {
    'primaryColor': '#e3f2fd',
    'primaryTextColor': '#0d47a1',
    'primaryBorderColor': '#1565c0',
    'lineColor': '#1e88e5',
    'edgeLabelBackground': '#e3f2fd'
} } }%%
graph TD
    %% ==================================================
    %% Style Definition (C4 Palette)
    %% ==================================================
    classDef person fill:#08427b,color:white,stroke:#052e56,stroke-width:2px;
    classDef container fill:#1168bd,color:white,stroke:#0b4d8c,stroke-width:2px;
    classDef containerDb fill:#1168bd,color:white,stroke:#0b4d8c,stroke-width:2px;

    %% ==================================================
    %% Nodes
    %% ==================================================
    USER["<b>Researcher</b><br/>[Person]<br/><br/>Starts Python script."]:::person

    APP["<b>Python Orchestrator</b><br/>[Container: Python 3.10+]<br/><br/>Automation script (ohare_run.py)<br/>and support libraries."]:::container

    MATCHER["<b>Matcher Service</b><br/>[Container: Docker Image]<br/><br/>Map-matching algorithm service<br/>exposed via HTTP/TCP."]:::container

    MONITORING["<b>Observability Stack</b><br/>[Container: Prometheus + cAdvisor]<br/><br/>Collects infrastructure metrics<br/>(CPU, RAM, Net)."]:::container

    STORAGE[("<b>File Storage</b><br/>[Container Db: Disk]<br/><br/>Input datasets and output files<br/>(CSV/JSON).")]:::containerDb


    %% ==================================================
    %% Relationships
    %% ==================================================
    
    USER -- "Executes CLI" ----> APP
    
    APP -- "Sends GPS Requests /<br/>Receives Matches<br/>[HTTP/TCP]" -----> MATCHER
    
    APP -- "Starts services and<br/>Queries Metrics<br/>[Docker API / HTTP]" -----> MONITORING
    
    APP -- "Reads/Writes data" -----> STORAGE
    
    MONITORING -- "Scrapes metrics<br/>[cAdvisor]" ----> MATCHER
```

### Level 3: Component Diagram

Focusing on the "Python Orchestrator" container, we detail its internal components.

```mermaid
%%{init: { 'theme': 'base', 'themeVariables': {
    'primaryColor': '#e3f2fd',
    'primaryTextColor': '#0d47a1',
    'primaryBorderColor': '#1565c0',
    'lineColor': '#1e88e5',
    'edgeLabelBackground': '#e3f2fd'
} } }%%
C4Component
    title Component Diagram - Python Orchestrator

    Container(app, "Python Orchestrator", "Application", "Internal components of the execution script.")

    Component(orch, "BenchmarkOrchestrator", "Class", "Coordinates general flow, setup, and aggregation.")
    Component(runner, "ExperimentRunner", "Class", "Executes the point streaming and latency measurement loop.")
    Component(emitter, "GPSStreamEmitter", "Class", "Simulates real-time GPS point sending (async generator).")
    Component(benchLib, "Bench Lib (ServiceManager)", "Module", "Manages Docker Compose (start/stop services).")
    Component(metricsLib, "Metrics Lib (PromExport)", "Module", "Interacts with Prometheus for data extraction.")
    Component(data, "Data Handler", "Class", "Data loading and preparation (Pandas/DuckDB).")

    Rel(orch, runner, "Uses")
    Rel(runner, emitter, "Consumes stream")
    Rel(orch, benchLib, "Manages services")
    Rel(orch, metricsLib, "Extracts metrics")
    Rel(orch, data, "Loads data")
```

```mermaid
%%{init: { 'theme': 'base', 'themeVariables': {
    'primaryColor': '#e3f2fd',
    'primaryTextColor': '#0d47a1',
    'primaryBorderColor': '#1565c0',
    'lineColor': '#1e88e5',
    'secondaryColor': '#bbdefb',
    'tertiaryColor': '#ffffff',
    'edgeLabelBackground': '#e3f2fd'
} } }%%
flowchart TB
  %% ====== BPMN-like styling ======
  classDef event fill:#ffffff,stroke:#111111,stroke-width:2px;
  classDef task fill:#f7f7f7,stroke:#111111,stroke-width:1px,rx:6,ry:6;
  classDef gateway fill:#ffffff,stroke:#111111,stroke-width:2px;
  classDef datastore fill:#ffffff,stroke:#111111,stroke-width:1px;
  classDef artifact fill:#ffffff,stroke:#111111,stroke-dasharray: 5 5,rx:6,ry:6;

  %% ====== Start and End ======
  start((Process Start)):::event
  end_ok((Dataset Finished)):::event

  %% ====== Lane 1 ======
  subgraph L1[Lane Road Network Acquisition and Preparation]
    direction TB
    t1[Extract road network with OSMnx<br/>O'Hare Chicago Area<br/>Type drive]:::task
    d1[Raw Road Network<br/>XML and GraphML formats]:::datastore
    t2[Filter highway entities with osmfilter]:::task
    d2[Filtered OSM Network]:::datastore
    t3[Convert network to SUMO with netconvert<br/>Preserve topology and OSM IDs]:::task
    a1[Visual Artifact of SUMO Network]:::artifact
    d3[Road Network ready for SUMO simulation]:::datastore
  end

  %% ====== Lane 2 ======
  subgraph L2[Lane Trip Generation and Simulation]
    direction TB
    t4[Generate trips with randomTrips.py<br/>Seed 42<br/>Duration 1 hour<br/>Insertion every 2 seconds<br/>Min distance 500 meters]:::task
    d4[Generated Trips and Routes]:::datastore
    t5[Run SUMO simulation<br/>Shortest path route calculation<br/>Time step 0.5 seconds]:::task
    t6[Collect data via TraCI<br/>Vehicle time position speed]:::task
    d5[Raw Ground Truth<br/>Exact trajectory on network]:::datastore
  end

  %% ====== Lane 3 ======
  subgraph L3[Lane Post-processing and GNSS Generation]
    direction TB
    t7[Reconstruct mapping between SUMO lanes and OSM edges<br/>Handle automatic junctions<br/>Reconnect gaps with shortest path]:::task
    d6[Consistent Ground Truth<br/>Referenced to OSM graph]:::datastore
    t8[Generate Noisy GNSS Measurements<br/>Gaussian 2D Noise<br/>Std Dev 5 meters]:::task
    d7[Simulated GNSS Measurements]:::datastore
    t9[Persist final data in Parquet format]:::task
    d8[Final Ground Truth Dataset]:::datastore
    d9[Final Noisy GNSS Dataset]:::datastore
  end

  %% ====== Lane 4 ======
  subgraph L4[Lane Validation and Benchmark Suitability]
    direction TB
    t10[Preliminary Validation<br/>Manual sample inspection<br/>Comparison with GraphHopper]:::task
    g1{Topological integrity and viability confirmed}:::gateway
    t11[Adjust network or mapping<br/>Fix detected inconsistencies]:::task
    t12[Final Benchmark Validation<br/>Evaluate heterogeneity among SUTs]:::task
    g2{Dataset exposes differences between SUTs}:::gateway
    t13[Adjust dataset parameters<br/>Noise generation or filtering]:::task
  end

  %% ====== Main Flow ======
  start --> t1 --> d1 --> t2 --> d2 --> t3 --> a1 --> d3
  d3 --> t4 --> d4 --> t5 --> t6 --> d5
  d5 --> t7 --> d6 --> t8 --> d7 --> t9 --> d8 --> end_ok
  t9 --> d9 --> end_ok

  %% ====== Validation Loops ======
  t9 --> t10 --> g1
  g1 -- No --> t11 --> t7
  g1 -- Yes --> t12 --> g2
  g2 -- No --> t13 --> t4
  g2 -- Yes --> end_ok

```
