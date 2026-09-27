flowchart TD
    Client[Client / Frontend] --> API[API Service\nSpring Boot]
    
    API --> DB[(PostgreSQL)]
    API --> Cache[(Redis)]
    
    DB --> Kafka{Kafka Queue}
    
    Kafka --> W1[Worker 1]
    Kafka --> W2[Worker 2]
    Kafka --> W3[Worker 3]
    
    W1 --> S1[Docker Sandbox 1]
    W2 --> S2[Docker Sandbox 2]
    W3 --> S3[Docker Sandbox 3]
    
    S1 --> Storage[Artifact Storage]
    S2 --> Storage
    S3 --> Storage