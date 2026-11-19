# Deployment acceptance and operational targets

This is a checklist for the owner's private installation. It does not require publishing data, changing the existing installation, or attaching screenshots/logs to issues. Local synthetic tests cannot establish vendor export behavior, device scheduling or live hosted-client compatibility.

## Proposed single-owner operating targets

- A matching ingest acknowledgment means its database transaction committed. A crash before checkpoint persistence may replay a batch but must not duplicate measurements.
- Background phone work yields within approximately four minutes and resumes from a durable checkpoint. Hourly scheduling is best effort under Android power/network policies, not a guarantee that vendor records arrive hourly.
- Review service health and source freshness at least daily. A successful sync does not prove complete wearable coverage.
- Target backup RPO is 24 hours only after a daily encrypted backup job is configured and monitored. Target recovery time is one hour for the owner's dataset, to be demonstrated in a private restore drill. Until measured, these are targets rather than achieved service levels.

## Required private acceptance before production promotion

1. Upgrade the phone with its existing signing identity; do not uninstall or clear app storage. Confirm pairing, permissions and the saved queue/cursors survive the upgrade.
2. Exercise foreground/background sync, network interruption, process termination, reboot and retry. Verify stable batch IDs and one stored record per source/record identity. Test denied/revoked permissions and expired Health Connect cursors; no silent reset is allowed.
3. Verify Garmin and Zepp each export supported records into Health Connect on the actual device/account. Availability depends on vendor, platform, region and permissions.
4. Verify TLS and private-network access, rejected unauthorized requests, identity-header replacement at the trusted proxy, and absence of public database/context listeners. On native Linux, evaluate the `dashboard-private` Unix-socket profile. On this Mac, the Docker Desktop bind-mounted socket failed acceptance; the native-host candidate also returned 502 through standalone Tailscale 1.104.7, with a network-extension socket permission denial. Neither macOS route is accepted; see setup.md for the deployment alternatives. Check the Serve proxy actually connects to the chosen socket, and verify no TCP listener is published for the dashboard. Treat this as a live-host gate, not a CI success.
5. Open the MCP dashboard in the intended hosted client, switch views and refresh. Confirm only read tools are exposed to the UI; separately verify explicit write scope only where desired.
6. Restore encrypted MySQL, context and photo backups into a separate empty installation; compare counts/checksums and confirm permissions. Never test by replacing the live database.
7. Review current container advisories and Android lint compatibility warnings, record the supported phone/OS matrix, and measure response times with the intended private dataset.

## Upgrade and rollback

Keep the previous source revision, private configuration and signing key securely. Pause writers before schema changes, take a verified backup, and run migration checks against a separate restored copy first. Deploy the candidate only after those checks and device acceptance. Restart services for token/config changes and inspect freshness privately.

Rollback application code only when the schema and committed writes remain compatible. Once new data is acknowledged, do not restore an older database or reset phone cursors as a shortcut: reconcile newer records/receipts first. Do not run Compose volume deletion against a live installation. No automatic deployment or production migration is included in CI.
