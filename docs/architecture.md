# Architecture and trust boundaries

```mermaid
flowchart TB
    subgraph Vendor[External vendor systems]
        GC[Garmin Connect]
        Z[Zepp]
    end
    subgraph Phone[Android device]
        HC[Health Connect]
        App[Private Fitness 0.6.2]
        Queue[Private durable outbox and checkpoints]
        Key[Keystore-protected pairing token]
        HC --> App --> Queue
        Key --> App
    end
    GC --> HC
    Z --> HC
    subgraph Host[Private host]
        Proxy[Private HTTPS proxy]
        API[Bearer-authenticated ingestion]
        SQL[(MySQL: wearable records and receipts)]
        GS[Garmin cache schema; no direct adapter bundled]
        Cache[(MySQL: Garmin cache)]
        Ctx[Capability-protected context API]
        CDB[(SQLite context and attachments)]
        MCP[Fitness stdio MCP]
        Bridge[Combined stdio bridge and UI overlay]
        Web[Browser dashboard]
        Logs[(MySQL manual logs and local photos)]
        Proxy --> API --> SQL
        GS --> Cache
        SQL --> MCP
        Cache --> MCP
        CDB <--> Ctx
        Ctx <--> Bridge
        MCP --> Bridge
        Proxy --> Web
        SQL --> Web
        Logs <--> Web
    end
    Queue -->|HTTPS and matching batch ACK| Proxy
    Bridge --> Client[Authorized local or hosted assistant]
```

The phone receives only an ingestion capability, never database credentials. Host-side SQL separates writer, reader, Garmin-sync and browser-log roles. Context uses separate read/write capability files. Stdio client configs reference launchers rather than tokens.

MySQL is bound to host loopback for host services. The browser connects over the Compose network using its limited roles. Ingestion/context bind loopback; only selected ingestion/browser routes are exposed through private HTTPS. Same-user host processes remain inside the trust boundary. Local files and Compose secrets are not an encrypted secret manager.

An assistant tool call is an outbound disclosure of returned data to that client. The optional hosted tunnel is outside this repository's ownership and is not bundled. Authentication does not mean a hosted provider sees no health data.

The two dashboards intentionally have different data stores: the browser owns manual logs/photos, while the MCP UI reads context meals/plans. No silent reconciliation connects those stores. The direct Garmin cache also remains separate from daily Health Connect metrics.
