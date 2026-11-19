# Private Fitness: an end-to-end personal data system

By [David Villero](https://github.com/DavidVillero), with AI-assisted implementation.

Fitness integrations become difficult where data crosses boundaries: from a watch into a vendor app, from that app into a phone platform, and from local records into an assistant. Private Fitness makes those boundaries explicit rather than treating everything as one interchangeable stream.

An Android bridge reads permitted Garmin and Zepp records from Health Connect. It preserves source identities, persists an outbox before upload, and records progress only after the host acknowledges the corresponding batch. A local ingestion service validates the batch and writes it transactionally. Retry handling, revision checks and deletion tombstones protect against duplicate counting and stale updates.

The query layer treats absence as unknown. It selects sources independently for daily metrics and handles overlapping activity recordings separately. An optional Garmin workout-detail cache is kept separate and is never added to Health Connect totals. Coverage and quality notes travel with query results.

A local context service stores explicitly saved plans, meals, notes and attachments with revisions and provenance. Its MCP bridge combines saved context with read-only fitness tools. Clients start with read access; saving records requires a deliberately enabled write capability and explicit tool arguments. Browser manual logs and context meals remain separate stores, a limitation the interfaces expose.

The system has both a private browser dashboard and an embedded MCP App interface. The embedded interface supports MCP Apps and ChatGPT host bridges and has synthetic browser tests. Acceptance in the actual hosted client remains a separate deployment step. The phone source includes durable upload checkpoints and controls for optional background sync, whose timing remains under Android's control.

Local storage is only part of the privacy story. Vendor apps may synchronize with their vendors, and an authorized hosted assistant receives tool results. The project therefore separates credentials, restricts database roles, keeps network listeners local behind private HTTPS, and avoids embedding records in UI assets or source configuration.

The source release contains fresh-install templates and empty schema definitions, not someone's running installation. Health histories, credentials, databases, screenshots, signing keys and private binaries are excluded. Reusable integrations remain documented, while external vendor apps and hosted tunnel tooling must be supplied separately.

The design is intentionally inspectable: preserve origins, acknowledge before advancing, separate capabilities, and keep uncertainty visible. It is not a claim of clinical validity, complete wearable coverage, or effortless deployment on every device.

## Evidence and limits

The reviewed source candidate passed 125 Python tests, 24 Android unit tests, four host-adapter tests, a debug Android build and synthetic Chromium checks across five views at mobile and desktop widths. A separate Android 17 acceptance check verified an in-place upgrade with preserved pairing/queued state and advancing live upload acknowledgments. Full sync completion and hosted-client acceptance remain pending. See [validation](validation.md) and [security status](security-status.md) for reproducible checks and remaining limitations, including upstream container OS advisories.

The project demonstrates Android ingestion, transactional storage, capability-scoped MCP tools and assistant UI integration in one inspectable system. Further device lifecycle checks and independent fresh wearable export verification remain documented follow-up work. No clinical validity, vendor approval or product-market fit is claimed.

## Discuss the work

I welcome conversations about privacy-conscious fitness integrations, AI engineering and potential collaborations. Contact [David Villero](https://github.com/DavidVillero) through the public profile or a non-sensitive repository issue. Do not share personal health data or credentials in public issues.

This independent project is not affiliated with or endorsed by Garmin, Google, Zepp or OpenAI. Source is published for portfolio review without an open-source license grant; see [rights and vendor boundaries](rights-and-vendors.md).
