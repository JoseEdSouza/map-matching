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
%%{init: { 'theme': 'base', 'themeVariables': {
    'primaryColor': '#e1f5fe',
    'primaryTextColor': '#000',
    'primaryBorderColor': '#1168bd',
    'lineColor': '#333',
    'secondaryColor': '#f5f5f5',
    'tertiaryColor': '#fff'
} } }%%

sequenceDiagram
    autonumber
    
    %% Participantes com nomes em Português
    participant User as 👤 Pesquisador
    participant Orch as ⚙️ Benchmark<br/>Orchestrator
    participant Stack as 📊 Stack de Métricas<br/>(Prom/cAdvisor)
    participant Runner as 🏃 ExperimentRunner
    participant Docker as 🐳 Docker Compose
    participant Matcher as 🧩 Matcher Container
    participant Out as 📁 OutputManager

    Note over Orch, Runner: Framework Principal (Python)
    Note over Stack, Docker: Serviços de Infraestrutura
    Note over Matcher: Algoritmo Alvo

    User->>Orch: Iniciar Benchmark (run_all_experiments)
    
    Orch->>Stack: track_metrics() (Inicia Prometheus)
    activate Stack
    
    rect rgb(240, 248, 255)
    Note right of Orch: Loop: Para cada Veículo / Taxa de Amostragem / Configuração
    
        Orch->>Docker: launch_service() (Inicia Matcher)
        activate Matcher
        Docker-->>Orch: ID do Experimento
        
        Orch->>Runner: run_single_experiment()
        activate Runner
        
        Runner->>Runner: GPSStreamEmitter (Simula Stream)
        
        loop Fluxo de Pontos (Stream)
            Runner->>Matcher: Envia Ponto/Lote (Requisição)
            Matcher-->>Runner: Resultado do Matching (Resposta)
            Runner->>Runner: Registra Latência E2E
        end
        
        Runner-->>Orch: Resultados do Matching e Métricas E2E
        deactivate Runner

        Orch->>Docker: Parar Serviço
        deactivate Matcher
        
        Orch->>Stack: export_prometheus_timeseries()
        Stack-->>Orch: Métricas de CPU/RAM/Rede
        
        Orch->>Out: Salvar Relatório Individual
    end
    
    Orch->>Stack: Parar Stack de Métricas
    deactivate Stack
    
    Orch->>Out: Salvar Métricas Agregadas
    Orch-->>User: Execução Finalizada
```

### Arquitetura de Componentes (Class Diagram)

Este diagrama mostra a relação entre as classes Python e os módulos do sistema.

```mermaid
%%{init: { 'theme': 'base', 'themeVariables': {
    'primaryColor': '#ffffff',
    'primaryBorderColor': '#1168bd',
    'lineColor': '#333333',
    'tertiaryColor': '#f4f4f4',
    'fontFamily': 'arial'
} } }%%

classDiagram
    direction TB

    %% --- Styling ---
    classDef core fill:#e1f5fe,stroke:#01579b,stroke-width:2px;
    classDef infra fill:#f5f5f5,stroke:#9e9e9e,stroke-width:2px;
    classDef storage fill:#fff9c4,stroke:#fbc02d,stroke-width:2px;
    classDef config fill:#ffffff,stroke:#333,stroke-dasharray: 5 5;

    %% --- Hierarquia Vertical ---

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

    %% --- Relationships (Ordenados para forçar verticalidade) ---
    
    BenchmarkOrchestrator o-- MatcherConfig : "possui"
    BenchmarkOrchestrator --> DataLoader : "carrega dados"
    
    BenchmarkOrchestrator --> ExperimentRunner : "dispara"
    ExperimentRunner --> GPSStreamEmitter : "gera stream"
    ExperimentRunner ..> MatcherConfig : "consome"

    BenchmarkOrchestrator --> BenchModule : "controla infra"
    BenchModule ..> DockerCompose : "via subprocess"

    BenchmarkOrchestrator --> OutputManager : "exporta"

    %% --- Notas Estreitas ---
    note for BenchmarkOrchestrator "Ponto de entrada.<br/>Lê as configs e<br/>gerencia o fluxo."
    note for BenchModule "Lida com o ciclo de<br/>vida do Docker e<br/>coleta de métricas."
    note for GPSStreamEmitter "Simula envio de<br/>dados em real-time."
```

### Fluxo de Dados de Métricas

Como as métricas são coletadas de diferentes fontes e unificadas.

```mermaid
%%{init: { 'theme': 'base', 'themeVariables': {
    'primaryColor': '#ffffff',
    'primaryBorderColor': '#1168bd',
    'lineColor': '#333333',
    'fontFamily': 'arial'
} } }%%

graph TD
    %% --- Estilos ---
    classDef app fill:#e1f5fe,stroke:#01579b,stroke-width:2px;
    classDef infra fill:#f5f5f5,stroke:#9e9e9e,stroke-width:2px;
    classDef result fill:#fff9c4,stroke:#fbc02d,stroke-width:2px;

    %% --- Nível 1: Coleta de Dados (Lado a Lado) ---
    subgraph APP [🐍 Aplicação Python]
        direction TB
        Runner[ExperimentRunner]:::app
        E2E_Metrics[Métricas E2E<br/>Latência/Throughput]:::app
        MatcherResult[Resultado do Matching]:::app
        Match_Metrics[Métricas de Qualidade<br/>Acurácia/Erros]:::app
        
        Runner ----> E2E_Metrics
        MatcherResult ----> Match_Metrics
    end

    subgraph INFRA [🐳 Infraestrutura Docker]
        direction TB
        Container[Matcher Service]:::infra
        CADVISOR[cAdvisor]:::infra
        PROM[Prometheus]:::infra
        
        Container -- "Uso de Recursos" ----> CADVISOR
        CADVISOR -- "Scrape" ----> PROM
    end

    %% --- Nível 2: Extração de Métricas de Sistema ---
    PROM -- "Query Range API" ----> PromExport[bench/prom_export.py]:::app
    PromExport -- "DataFrames" ----> Sys_Metrics[Métricas de Sistema<br/>CPU/Mem/Rede]:::app

    %% --- Nível 3: Agregação e Join ---
    E2E_Metrics ----> Aggregator{MetricsAggregator}:::app
    Match_Metrics ----> Aggregator
    Sys_Metrics ----> Aggregator

    %% --- Nível 4: Saída ---
    Aggregator -- "Join por ExperimentID" ----> FinalCSV[(Relatórios Consolidados CSV)]:::result

    %% Ajuste de bordas dos subgráficos
    style APP fill:none,stroke:#01579b,stroke-dasharray: 5 5
    style INFRA fill:none,stroke:#9e9e9e,stroke-dasharray: 5 5
```

---

## Modelagem C4

Abaixo apresentamos a arquitetura do sistema utilizando o modelo C4 (Context, Containers, Components).

### Nível 1: Diagrama de Contexto (Context Diagram)

O diagrama de contexto situa o Sistema de Benchmarking em relação aos usuários e sistemas externos.

```mermaid
graph TD
    %% Definição de Estilos C4
    classDef person fill:#08427b,color:white,stroke:#052e56,stroke-width:2px;
    classDef system fill:#1168bd,color:white,stroke:#0b4d8c,stroke-width:2px;
    classDef external fill:#999999,color:white,stroke:#666666,stroke-width:2px;

    %% Nós (Nodes)
    USER["<b>Pesquisador / Desenvolvedor</b><br/>[Pessoa]<br/><br/>Configura e executa<br/>experimentos."]:::person
    
    BENCH["<b>Benchmark Framework</b><br/>[Sistema Software]<br/><br/>Orquestra experimentos,<br/>simula dados e coleta métricas."]:::system

    DOCKER["<b>Docker Engine</b><br/>[Sistema Externo]<br/><br/>Gerencia a execução<br/>dos containers."]:::external

    FS["<b>Sistema de Arquivos</b><br/>[Sistema Externo]<br/><br/>Armazena datasets<br/>e resultados."]:::external

    %% Relacionamentos com setas longas (----->) para dar espaço ao texto
    USER -- "Inicia experimentos" -----> BENCH
    BENCH -- "Gerencia ciclo de<br/>vida dos serviços" ----> DOCKER
    BENCH -- "Lê dados e<br/>grava relatórios" ----> FS

    %% Ajuste de layout lateral
    direction TB
```

### Nível 2: Diagrama de Containers (Container Diagram)

Este nível detalha as aplicações e serviços executáveis que compõem o sistema.

```mermaid
graph TD
    %% ==================================================
    %% Definição de Estilos (C4 Palette)
    %% ==================================================
    classDef person fill:#08427b,color:white,stroke:#052e56,stroke-width:2px;
    classDef container fill:#1168bd,color:white,stroke:#0b4d8c,stroke-width:2px;
    %% ContainerDB usa a mesma cor, mas mudaremos a forma no nó
    classDef containerDb fill:#1168bd,color:white,stroke:#0b4d8c,stroke-width:2px;

    %% ==================================================
    %% Nós (Nodes) com rótulos HTML
    %% ==================================================
    USER["<b>Pesquisador</b><br/>[Pessoa]<br/><br/>Inicia o script Python."]:::person

    APP["<b>Python Orchestrator</b><br/>[Container: Python 3.10+]<br/><br/>Script de automação (ohare_run.py)<br/>e bibliotecas de suporte."]:::container

    MATCHER["<b>Matcher Service</b><br/>[Container: Docker Image]<br/><br/>Serviço do algoritmo de map-matching<br/>exposto via HTTP/TCP."]:::container

    MONITORING["<b>Observability Stack</b><br/>[Container: Prometheus + cAdvisor]<br/><br/>Coleta métricas de infraestrutura<br/>(CPU, RAM, Rede)."]:::container

    %% Nota: O uso de [( e )] cria a forma de banco de dados/armazenamento
    STORAGE[("<b>File Storage</b><br/>[Container Db: Disk]<br/><br/>Datasets de entrada e arquivos<br/>de saída (CSV/JSON).")]:::containerDb


    %% ==================================================
    %% Relacionamentos com setas longas (---->) e quebras de linha (<br/>)
    %% ==================================================
    
    USER -- "Executa CLI" ----> APP
    
    %% Relações principais do OrchestratoR
    %% Usei 5 traços (----->) para forçar mais espaço vertical aqui
    APP -- "Envia Requests GPS /<br/>Recebe Matches<br/>[HTTP/TCP]" -----> MATCHER
    
    APP -- "Inicia serviços e<br/>Consulta Métricas<br/>[Docker API / HTTP]" -----> MONITORING
    
    APP -- "Lê/Escreve dados" -----> STORAGE
    
    %% Relação lateral entre containers
    MONITORING -- "Scrapes metrics<br/>[cAdvisor]" ----> MATCHER
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


```mermaid
flowchart TB
  %% ====== BPMN-like styling ======
  classDef event fill:#ffffff,stroke:#111111,stroke-width:2px;
  classDef task fill:#f7f7f7,stroke:#111111,stroke-width:1px,rx:6,ry:6;
  classDef gateway fill:#ffffff,stroke:#111111,stroke-width:2px;
  classDef datastore fill:#ffffff,stroke:#111111,stroke-width:1px;
  classDef artifact fill:#ffffff,stroke:#111111,stroke-dasharray: 5 5,rx:6,ry:6;

  %% ====== Start and End ======
  start((Início do processo)):::event
  end_ok((Dataset finalizado)):::event

  %% ====== Lane 1 ======
  subgraph L1[Lane Aquisição e Preparação da Malha Viária]
    direction TB
    t1[Extrair rede viária com OSMnx<br/>Área O'Hare Chicago<br/>Tipo drive]:::task
    d1[Rede viária bruta<br/>Formatos XML e GraphML]:::datastore
    t2[Filtrar entidades highway com osmfilter]:::task
    d2[Rede OSM filtrada]:::datastore
    t3[Converter rede para SUMO com netconvert<br/>Preservar topologia e IDs OSM]:::task
    a1[Artefato visual da rede no SUMO]:::artifact
    d3[Rede viária pronta para simulação no SUMO]:::datastore
  end

  %% ====== Lane 2 ======
  subgraph L2[Lane Geração de Viagens e Simulação]
    direction TB
    t4[Gerar viagens com randomTrips.py<br/>Seed 42<br/>Duração 1 hora<br/>Inserção a cada 2 segundos<br/>Distância mínima 500 metros]:::task
    d4[Viagens e rotas geradas]:::datastore
    t5[Executar simulação no SUMO<br/>Cálculo de rotas por menor caminho<br/>Passo temporal 0.5 segundos]:::task
    t6[Coletar dados via TraCI<br/>Veículo tempo posição via]:::task
    d5[Ground truth bruto<br/>Trajetória exata sobre a rede]:::datastore
  end

  %% ====== Lane 3 ======
  subgraph L3[Lane Pós-processamento e Geração GNSS]
    direction TB
    t7[Reconstruir mapeamento entre vias SUMO e arestas OSM<br/>Tratar junções automáticas<br/>Reconectar lacunas com menor caminho]:::task
    d6[Ground truth consistente<br/>Referenciado ao grafo OSM]:::datastore
    t8[Gerar medições GNSS ruidosas<br/>Ruído gaussiano bidimensional<br/>Desvio padrão 5 metros]:::task
    d7[Medições GNSS simuladas]:::datastore
    t9[Persistir dados finais em formato Parquet]:::task
    d8[Dataset final ground truth]:::datastore
    d9[Dataset final GNSS ruidoso]:::datastore
  end

  %% ====== Lane 4 ======
  subgraph L4[Lane Validação e Adequação ao Benchmark]
    direction TB
    t10[Validação preliminar<br/>Inspeção manual de amostra<br/>Comparação com GraphHopper]:::task
    g1{Integridade topológica e viabilidade confirmadas}:::gateway
    t11[Ajustar rede ou mapeamento<br/>Corrigir inconsistências detectadas]:::task
    t12[Validação final no benchmark<br/>Avaliar heterogeneidade entre ferramentas]:::task
    g2{Dataset expõe diferenças entre SUTs}:::gateway
    t13[Ajustar parâmetros do dataset<br/>Geração ruído ou filtragem]:::task
  end

  %% ====== Fluxo principal ======
  start --> t1 --> d1 --> t2 --> d2 --> t3 --> a1 --> d3
  d3 --> t4 --> d4 --> t5 --> t6 --> d5
  d5 --> t7 --> d6 --> t8 --> d7 --> t9 --> d8 --> end_ok
  t9 --> d9 --> end_ok

  %% ====== Loops de validação ======
  t9 --> t10 --> g1
  g1 -- Não --> t11 --> t7
  g1 -- Sim --> t12 --> g2
  g2 -- Não --> t13 --> t4
  g2 -- Sim --> end_ok

```