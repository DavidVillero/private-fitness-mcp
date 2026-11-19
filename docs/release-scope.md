# Release scope and sanitization

The distribution includes the end-to-end project source and fresh-install configuration: Android app 0.6.2, Health Connect ingestion, MySQL/SQLite adapters and schema definitions, Garmin cache schema/read tools (direct sync omitted), personal-context service, fitness/context/combined MCP bridges, embedded and browser dashboards, tests, launchers, dummy configuration and setup/operation guides.

Removed or generalized:

- Personal hostnames, login identity, home-directory paths, activity identifiers, embedded workout schedule/goals, saved correction references and observed-value test fixtures.
- Hardwired private interpreter/toolchain paths and assumptions that a pre-existing context/tunnel installation exists.
- Default write-scoped combined/dashboard launch; the export defaults to read, with explicit opt-in write scope.
- Machine-specific deployment/cutover scripts and their private inventories. Reusable setup, migration, backup and client configuration replace those one-off operations.

Excluded entirely: real health/context records, conversation snapshots, photos/screenshots, reports, databases/dumps, credential/session files, keys/certificates, signed APKs, downloaded dependencies, private/proprietary binaries and original Git history. SQL files that remain are **schema source**, not database dumps. Inline test values are artificial inputs, not exported health data.

The new initializer generates fresh private runtime files only when the operator runs it. Filled configuration, generated SQL containing credentials, databases, reports, caches and build outputs are ignored. Ignore rules alone are not a publication guarantee: inspect the exact allowlisted files and hashes before each push.

The original deployment is not modified or migrated by preparing this export. External vendor apps and an optional hosted provider tunnel still require the operator's own installation/accounts. Removing proprietary binaries does not remove their external service boundaries from the architecture.

Known acceptance gaps include live hosted MCP App testing, vendor export variability, direct Garmin API stability, seven-day phone initial import, separate browser/context logs, and unverified new-device pairing/full deployment in this review. See [validation](validation.md).
