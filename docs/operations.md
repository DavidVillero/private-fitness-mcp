# Operations

## Startup and scheduling

Start MySQL, ingestion and context before using the full MCP bridge. The browser is optional. Host launchers use the checkout's `.venv`; they never depend on an original machine path. Mac sleep, OS login, Docker availability, private networking and credential expiration affect unattended operation.

`config/launchd.example.plist` is a dummy macOS job template. Make private local copies with unique labels and real absolute paths. Create a private `logs/` directory first. Use the following launcher arguments:

| Job | Launcher arguments | Scheduling |
| --- | --- | --- |
| Ingestion | `ingest` | Long-running; replace interval with KeepAlive |
| Context | `context` | Long-running; replace interval with KeepAlive |
| Local reports | `reports` | Optional interval or calendar schedule |
| Context backup | `context-backup` | Optional daily interval/calendar schedule |

For persistent services use `<key>KeepAlive</key><true/>` instead of `StartInterval`. Load only your new labels with `launchctl bootstrap gui/$(id -u) /absolute/path/to/your-job.plist`. The checked-in example is not installed automatically. Linux users can run equivalent user services with the same launcher, working directory and owner-only file permissions. Provider tunnel process supervision follows that provider's instructions; no proprietary process manager is included.

Set timezone consistently in root `.env` (Compose) and `deploy/runtime.local.json` (host launchers). An explicit `FITNESS_TIMEZONE` environment variable overrides the host setting. Runtime source priorities may be copied from the source-priorities example into the service's ignored `config/source-priorities.json`.

## Verification without publishing data

Check process status and authentication first. Unauthenticated ingestion should return 401; context `/tools` should return 401. Context `/health` reports service integrity without record contents. MySQL should publish only loopback. Test MCP initialization/discovery before querying personal records. Then use a user-authorized phone sync and inspect results privately. Do not attach responses, diagnostic exports or screenshots to public issues.

## Backup and restore

Back up the MySQL schemas, dashboard photo directory, context SQLite/attachments, and configuration using your own encrypted storage policy. Keep credentials separate and private. A persistent Docker volume is not a backup.

The context service includes a consistency-aware backup command:

```sh
scripts/run context-backup
```

It writes an ignored local backup directory with an integrity manifest. A restore must target a new directory, never the live store:

```sh
# Run from services/personal-context with the project virtualenv active.
python -m context_service.admin restore /absolute/path/to/private-backup /absolute/path/to/new-restore-directory
```

Inspect the restored data privately before changing runtime configuration. The generic context admin CLI also exposes explicit JSON export, supplied conversation imports, soft deletion and schema migration; it does not discover private chats automatically.

For MySQL, use a consistent transaction-based dump or a database-aware backup tool and test restoration into a separate empty instance. Include all three logical stores: wearable/receipt tables, Garmin cache/state, and browser manual logs. Coordinate dashboard photo copies with writes so references and files remain consistent. No production dump or backup script tied to an old machine is included.

## SQLite-to-MySQL migration

`services/private-fitness-mcp/scripts/migrate_mysql.py` preserves records, revisions, tombstones and receipts, checks ordered fingerprints, and refuses a non-empty target. It does not switch the active config. Use an explicit private source, snapshot path and candidate config after pausing ingestion; its `--after-approval` flag is an operator acknowledgment for migration. Do not run it on a new empty install unless you actually have a source database to migrate.

If new batches have reached MySQL, switching to an older SQLite snapshot can lose data relative to phone cursors. Reconcile new records/receipts before rollback. Never run `docker compose down -v` against a volume containing data you intend to preserve.

Context capability files are validated at service startup and cached in memory. Use distinct random read/write tokens of at least 32 ASCII characters. After rotating them locally, restart the context service; changing or truncating a file does not alter the running service capability.

## Failure and retention behavior

The phone retries transient network/server failures and keeps its outbox. Expired Health Connect tokens trigger a 30-day re-snapshot with a persistent warning about missed deletions and older modifications; success does not prove complete reconciliation. Changed permission sets still halt the affected stream pending manual review. No direct Garmin sync adapter ships in this source; any future adapter requires separate vendor-access review. Unknown coverage remains explicit.

Deleting a context record is initially a soft deletion; versions, attachments and backups may retain it. Physical purge is an explicit separate operation in `context_service.retention`. Browser meal deletion does not automatically erase photos. Cached Garmin workout records are not automatically removed. Define a retention policy before storing long-term personal data.


## Oversized phone data

Supported uploads are at most 2,000,000 UTF-8 bytes per envelope, at most 1,000 records/deletions, and at most 10,000 samples in a heart-rate record. The phone now batches by actual serialized bytes. Older oversized multi-record outboxes are atomically split before transmission, retaining acknowledged prefix entries and source record IDs. Split batch IDs are deterministic so an interrupted repair or lost acknowledgment is safe to replay.

An individual record that exceeds these limits is **not truncated, resampled, silently discarded or given a new identity**. The app reports that source-record recovery needs attention; it preserves its cursor and any existing outbox, and other independent source streams can still run. When detected before the outbox is created, correct the unsupported source record in the originating system and retry. For a previously persisted unsupported record, preserve a private backup of the outbox/checkpoint and arrange a reviewed reconciliation or protocol extension; editing the source alone does not replace that persisted envelope. Do not clear storage, hand-edit the queue, or reset a cursor to bypass the issue. Automatic fragmentation of a single measurement is deliberately unsupported because it would change update/deletion semantics.

See [deployment acceptance](deployment-acceptance.md) for device lifecycle, backup and rollback gates. These gates apply to promotion of this source candidate; they do not authorize altering a live installation.

Expired-token history gaps require the [reconciliation procedure](history-reconciliation.md); a successful bounded reread does not resolve missed deletions.
