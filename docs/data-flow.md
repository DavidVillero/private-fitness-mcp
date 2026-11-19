# Data flow and persistence

```mermaid
sequenceDiagram
    participant HC as Health Connect
    participant Phone as Phone bridge
    participant Queue as Durable outbox
    participant API as Ingestion API
    participant DB as Wearable store
    Phone->>HC: Read allowed source-specific changes
    HC-->>Phone: Records, deletions and next cursor
    Phone->>Queue: Persist batches before sending
    loop Remaining batches
        Phone->>API: HTTPS batch with bearer token
        API->>API: Validate envelope, units, bounds and size
        API->>DB: Transaction with batch digest and revision checks
        DB-->>API: Accepted or duplicate batch
        API-->>Phone: ACK containing matching batch ID
        Phone->>Queue: Persist next-batch checkpoint
    end
    Phone->>Queue: Commit source cursor after acknowledgments
```

Reusing a batch ID with different content is rejected. Revisions update records only when newer; deletion tombstones prevent old retries from resurrecting records. Interrupted uploads keep queue state. Each source stream commits independently. A completion receipt records delivery, not complete wear/export coverage.

```mermaid
flowchart LR
    Query[Date, timezone, source] --> Read[Read-only query connection]
    Read --> Selection[Source priority and record eligibility]
    Selection --> Summary[Metric-specific summary]
    Summary --> Quality[Unknown values, provenance and limits]
    Quality --> MCP[JSON tool result]
    Context[Saved plans and corrections] --> Compare[Explicit confirmed associations]
    Garmin[Cached Garmin sets] --> Compare
    Compare --> MCP
```

Daily metrics choose sources per metric. Additive interval totals (steps, distance and calories) prefer greatest observed record duration, breaking ties by configured source priority; other interval metrics retain the relative-coverage rule and point metrics retain presence priority. Observed time does **not** establish wear or export completeness. Results include per-source observed fractions and flag steps excluded at midnight boundaries. Activity queries rank recordings per workout. Same-source overlaps are excluded and substantial cross-source overlap uses an 80-percent heuristic. Source comparisons are unpaired daily summaries. Unknown measurements are never invented from other sensor types.

Recovery queries include the requested end date. The dashboards request the previous day for recovery; scheduled reports currently use their report day. Choose a completed end date when avoiding an ongoing day matters. Optional user profiles are loaded only from an explicitly configured local file; no profile is supplied.

```mermaid
sequenceDiagram
    participant Client as Authorized MCP client
    participant Bridge as Combined stdio bridge
    participant Context as Loopback context API
    participant Store as Context SQLite
    Client->>Bridge: Explicit write tool with idempotency key
    Bridge->>Context: Write capability and request
    Context->>Context: Validate authorization and schema
    Context->>Store: Record, history and audit transaction
    Store-->>Context: Durable record and version
    Context-->>Bridge: Structured result
    Bridge-->>Client: Tool response
```

Context content remains data, not executable instructions. Backup/restore includes versions and linked attachment bytes; soft deletion retains history and old backups. Physical retention cleanup is a separate operator action.
