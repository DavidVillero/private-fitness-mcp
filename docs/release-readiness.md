# Source release and deployment status

The repository contains the Android bridge, ingestion service, database schemas, dashboards, MCP services, tests and fresh-install templates. The repository starts with a single source snapshot. Operators generate credentials during setup.

## What has been exercised

The November 16 review covered synthetic MySQL and dashboard workflows, Android unit tests and a debug build, browser host adapters and encrypted restore checks. A matching-signature Android upgrade preserved pairing and queued uploads. The backend acknowledged live batches. See the [validation results](validation.md) for the environments and evidence.

## What still needs a deployment check

- Confirm a complete phone sync, a new record from each wearable and background sync after reboot.
- Test the dashboard in the intended hosted MCP client. Verify private ingress and identity handling on the intended host. The native socket passed local checks, but the macOS Tailscale Serve socket route returned HTTP 502.
- Reconcile deletions that may have been missed after a Health Connect change token expired. Follow the [reconciliation guide](history-reconciliation.md).
- Rescan the chosen container images for the target architecture. The November 16 ARM64 scan found 31 medium and two unknown-severity matches in MySQL. See the [security status](security-status.md).
- Verify encrypted restoration, including photos, with an isolated destination on the intended deployment.

## Repository checks

The Verify workflow defines Python 3.12, Python 3.13 and Android jobs. Inspect a completed run to confirm the exact check names before applying the [example branch protection policy](../config/branch-protection.example.json). GitHub applies branch protection separately for each repository. See the [deployment acceptance checklist](deployment-acceptance.md) for host-specific verification.
