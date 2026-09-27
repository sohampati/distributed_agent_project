## Architecture

```mermaid
flowchart TD
    Client["Client / Agent"]
    
    API["API Service<br/>Spring Boot"]
    
    DB[("PostgreSQL<br/>Task State")]
    Redis[("Redis<br/>Ephemeral State")]
    Kafka[["Kafka<br/>Event Bus"]]
    
    Scheduler["Task Scheduler"]
    
    W1["Worker 1"]
    W2["Worker 2"]
    W3["Worker N"]
    
    S1["Docker Sandbox"]
    S2["Docker Sandbox"]
    S3["Docker Sandbox"]
    
    Agent["Agent Runtime<br/>Claude / OpenClaw / Local LLM"]
    
    Events["Execution Events"]
    
    Client -->|Submit / Query Tasks| API
    API --> DB
    API --> Scheduler
    
    Scheduler -->|Claim / Schedule| Kafka
    
    Kafka --> W1
    Kafka --> W2
    Kafka --> W3
    
    W1 --> S1
    W2 --> S2
    W3 --> S3
    
    S1 --> Agent
    S2 --> Agent
    S3 --> Agent
    
    W1 -->|Status / Results| DB
    W2 -->|Status / Results| DB
    W3 -->|Status / Results| DB
    
    W1 --> Events
    W2 --> Events
    W3 --> Events
    
    Events --> Kafka
    
    Scheduler --> Redis
    API --> Redis
```

### Core Components

| Component            | Responsibility                                                              |
| -------------------- | --------------------------------------------------------------------------- |
| **API Service**      | Accepts tasks, exposes task status, and provides execution history          |
| **PostgreSQL**       | Stores durable task state, worker assignments, leases, retries, and results |
| **Scheduler**        | Assigns tasks to workers and handles scheduling policies                    |
| **Kafka**            | Provides asynchronous task and execution-event communication                |
| **Workers**          | Execute tasks and manage agent runtimes                                     |
| **Docker Sandboxes** | Isolate each agent execution and limit resources                            |
| **Agent Runtime**    | Performs the actual coding task using Claude, OpenClaw, or a local LLM      |
| **Redis**            | Stores ephemeral coordination and fast-access state                         |
| **Execution Events** | Tracks task lifecycle, logs, failures, and worker activity                  |

### Execution Flow

```text
Client
  ↓
API Service
  ↓
PostgreSQL
  ↓
Scheduler
  ↓
Kafka
  ↓
Worker
  ↓
Docker Sandbox
  ↓
Agent Runtime
  ↓
Result / Events
  ↓
PostgreSQL + Kafka
```

The architecture is intentionally built around **reliable distributed execution** rather than the agent itself. The agent is treated as a workload that can be swapped independently from the underlying execution infrastructure.
