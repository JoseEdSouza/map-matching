# Arquitetura do Framework de Benchmarking de Map Matching

Este documento descreve a arquitetura do sistema de execução de benchmarks para algoritmos de map matching, conforme implementado nos módulos `bench` e no orquestrador `ohare_run.py`.

## Visão Geral

O sistema é um framework de avaliação automatizado projetado para testar diferentes soluções de map matching (como OSRM, GraphHopper, Barefoot, Graphium) sob condições controladas. Ele orquestra a execução de experimentos, gerencia o ciclo de vida de serviços via Docker, simula fluxos de dados GPS em tempo real e coleta métricas detalhadas de desempenho (latência, vazão) e consumo de recursos (CPU, memória, rede).

## Componentes Principais

### 1. Orquestrador (`BenchmarkOrchestrator`)
Localizado em `ohare_run.py`, é o componente central que coordena todo o processo.
- **Responsabilidades:**
  - Carregar configurações (`BenchmarkConfig`) e dados de teste (trajetórias e malha viária).
  - Iterar sobre as combinações de veículos, taxas de amostragem e algoritmos (matchers).
  - Gerenciar o fluxo de execução global (setup -> execução -> teardown -> relatórios).
  - Agregar resultados de múltiplos experimentos.

### 2. Executor de Experimentos (`ExperimentRunner`)
Responsável pela execução lógica de um único teste de map matching.
- **Responsabilidades:**
  - Simular o envio de pontos GPS em "tempo real" usando o `GPSStreamEmitter`, que respeita o `time_speed_factor`.
  - Interagir com a interface do *matcher* (que deve implementar `BaseOnlineMatcher`).
  - Coletar métricas de latência "fim-a-fim" (E2E) para cada ponto ou lote processado.

### 3. Gerenciador de Serviços (`bench` package)
Módulo responsável pela infraestrutura de execução baseada em containers.
- **`bench/start_services.py` (`launch_service`):** Um gerenciador de contexto que usa `docker compose` para iniciar containers específicos para cada *matcher* antes de um experimento e desligá-los logo após. Injeta configurações dinâmicas (como `DATASET_ID`, `EXPERIMENT_ID`) via variáveis de ambiente.
- **`bench/compose.py`:** Wrapper Python para comandos CLI do Docker Compose.

### 4. Sistema de Métricas e Observabilidade (`bench` package)
Coleta dados de desempenho do sistema durante a execução dos containers.
- **`bench/start_metrics.py` (`track_metrics`):** Inicia a pilha de monitoramento (Prometheus + cAdvisor) como serviços Docker.
- **`bench/prom_export.py`:** Consulta a API do Prometheus após cada experimento para extrair séries temporais de uso de CPU, memória e rede, associando-as ao ID do experimento.

### 5. Camada de Dados (`DataLoader` & `OutputManager`)
- **Entrada:** Lê arquivos Parquet (trajetórias ruidosas e ground truth) e GraphML (rede viária).
- **Saída:** Persiste métricas brutas e agregadas em CSV e JSON, organizadas por execução.

---

## Diagramas de Arquitetura

### Fluxo de Execução (Sequence Diagram)

O diagrama abaixo ilustra o ciclo de vida de um benchmark completo para um conjunto de veículos.

```mermaid
sequenceDiagram
    participant User
    participant Orch as BenchmarkOrchestrator
    participant Stack as Metrics Stack (Prom/cAdvisor)
    participant Runner as ExperimentRunner
    participant Docker as Docker Compose
    participant Matcher as Matcher Container
    participant Out as OutputManager

    User->>Orch: Iniciar Benchmark (run_all_experiments)
    Orch->>Stack: track_metrics() (Inicia Prometheus)
    activate Stack
    
    loop Para cada Veículo / Taxa de Amostragem / Matcher Config
        Orch->>Docker: launch_service() (Inicia Matcher)
        activate Matcher
        Docker-->>Orch: Experiment ID
        
        Orch->>Runner: run_single_experiment()
        activate Runner
        Runner->>Runner: GPSStreamEmitter (Simula Stream)
        loop Stream de Pontos GPS
            Runner->>Matcher: Envia Ponto/Lote (Request)
            Matcher-->>Runner: Resultado (Response)
            Runner->>Runner: Registra Latência E2E
        end
        Runner-->>Orch: Resultados do Matching & Métricas E2E
        deactivate Runner

        Orch->>Docker: Stop Service
        deactivate Matcher
        
        Orch->>Stack: export_prometheus_timeseries()
        Stack-->>Orch: Métricas de CPU/Mem/Net
        
        Orch->>Out: Salvar Relatório Individual
    end

    Orch->>Stack: Stop Metrics Stack
    deactivate Stack
    Orch->>Out: Salvar Métricas Agregadas
    Orch-->>User: Fim da Execuçãp
```

### Arquitetura de Componentes (Class Diagram)

Este diagrama mostra a relação entre as classes Python e os módulos do sistema.

```mermaid
classDiagram
    class BenchmarkOrchestrator {
        +BenchmarkConfig config
        +List~MatcherConfig~ matchers
        +DataLoader data_loader
        +ExperimentRunner runner
        +OutputManager output_mgr
        +run_all_experiments()
        +run_vehicle_matcher_experiment()
    }

    class ExperimentRunner {
        +run_single_experiment(matcher, gps_points)
    }

    class GPSStreamEmitter {
        +emit()
    }

    class BenchModule {
        <<Module>>
        +launch_service() context
        +track_metrics() context
        +export_prometheus_timeseries()
    }

    class MatcherConfig {
        +BaseOnlineMatcher matcher
        +String name
        +String services
        +String mode
    }

    class OutputManager {
        +save_individual_report()
        +save_aggregated_metrics()
    }

    BenchmarkOrchestrator --> ExperimentRunner : usa
    BenchmarkOrchestrator --> BenchModule : usa para infraestrutura
    BenchmarkOrchestrator --> OutputManager : usa para persistência
    BenchmarkOrchestrator o-- MatcherConfig : contém lista de
    ExperimentRunner --> GPSStreamEmitter : usa
    ExperimentRunner ..> MatcherConfig : executa matcher definido em
    BenchModule ..> DockerCompose : subprocess calls
```

### Fluxo de Dados de Métricas

Como as métricas são coletadas de diferentes fontes e unificadas.

```mermaid
graph LR
    subgraph "Aplicação Python"
        Runner[ExperimentRunner] -->|Latência, Throughput| E2E_Metrics[Métricas E2E]
        MatcherResult[Resultado do Matching] -->|Acurácia, Erros| Match_Metrics[Métricas de Qualidade]
    end

    subgraph "Infraestrutura Docker"
        Container[Matcher Service]
        cAdvisor[cAdvisor]
        Prometheus[Prometheus]
        
        Container -->|Uso de Recursos| cAdvisor
        cAdvisor -->|Scrape| Prometheus
    end

    Prometheus -->|Query Range API| PromExport[bench/prom_export.py]
    PromExport -->|DataFrames| Sys_Metrics[Métricas de Sistema CPU/Mem]

    E2E_Metrics --> Aggregator[MetricsAggregator]
    Match_Metrics --> Aggregator
    Sys_Metrics --> Aggregator

    Aggregator -->|Join por ExperimentID| FinalCSV[Relatórios Consolidados CSV]
```

---

## Modelagem C4

Abaixo apresentamos a arquitetura do sistema utilizando o modelo C4 (Context, Containers, Components).

### Nível 1: Diagrama de Contexto (Context Diagram)

O diagrama de contexto situa o Sistema de Benchmarking em relação aos usuários e sistemas externos.

```mermaid
C4Context
    title Diagrama de Contexto - Map Matching Benchmark Framework

    Person(user, "Pesquisador / Desenvolvedor", "Configura e executa experimentos de benchmarking.")
    
    System(benchSystem, "Benchmark Framework", "Orquestra experimentos, simula dados GPS e coleta métricas.")

    System_Ext(docker, "Docker Engine", "Gerencia a execução dos containers dos algoritmos e monitoramento.")
    System_Ext(filesystem, "Sistema de Arquivos", "Armazena datasets (Parquet), redes (GraphML) e resultados.")

    Rel(user, benchSystem, "Configura e Inicia")
    Rel(benchSystem, docker, "Gerencia ciclo de vida dos serviços")
    Rel(benchSystem, filesystem, "Lê dados e grava relatórios")
```

### Nível 2: Diagrama de Containers (Container Diagram)

Este nível detalha as aplicações e serviços executáveis que compõem o sistema.

```mermaid
C4Container
    title Diagrama de Containers - Map Matching Benchmark Framework

    Person(user, "Pesquisador", "Inicia o script Python")

    Container(app, "Python Orchestrator", "Python 3.10+", "Script de automação (ohare_run.py) e bibliotecas de suporte.")
    
    Container(matcher, "Matcher Service", "Docker Container", "Serviço do algoritmo de map-matching (ex: OSRM, Barefoot) exposto via HTTP/TCP.")
    
    Container(monitoring, "Observability Stack", "Prometheus + cAdvisor", "Coleta métricas de infraestrutura (CPU, RAM, Rede) dos containers.")
    
    ContainerDb(storage, "File Storage", "Disk", "Datasets de entrada e arquivos de saída (CSV/JSON).")

    Rel(user, app, "Executa CLI")
    Rel(app, matcher, "Envia Requests GPS / Recebe Matches", "HTTP/TCP")
    Rel(app, monitoring, "Inicia serviços e Consulta Métricas", "Docker API / HTTP")
    Rel(monitoring, matcher, "Scrapes metrics", "cAdvisor")
    Rel(app, storage, "Lê/Escreve dados")
```

### Nível 3: Diagrama de Componentes (Component Diagram)

Focando no container "Python Orchestrator", detalhamos seus componentes internos.

```mermaid
C4Component
    title Diagrama de Componentes - Python Orchestrator

    Container(app, "Python Orchestrator", "Application", "Componentes internos do script de execução.")

    Component(orch, "BenchmarkOrchestrator", "Class", "Coordena o fluxo geral, setup e agregação.")
    Component(runner, "ExperimentRunner", "Class", "Executa a lógica de loop de envio de pontos e medição de latência.")
    Component(emitter, "GPSStreamEmitter", "Class", "Simula o envio de pontos GPS em tempo real (async generator).")
    Component(benchLib, "Bench Lib (ServiceManager)", "Module", "Gerencia o Docker Compose (start/stop services).")
    Component(metricsLib, "Metrics Lib (PromExport)", "Module", "Interage com Prometheus para extração de dados.")
    Component(data, "Data Handler", "Class", "Carregamento e preparação de dados (Pandas/DuckDB).")

    Rel(orch, runner, "Usa")
    Rel(runner, emitter, "Consome stream")
    Rel(orch, benchLib, "Gerencia serviços")
    Rel(orch, metricsLib, "Extrai métricas")
    Rel(orch, data, "Carrega dados")
```
