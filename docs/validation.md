# Validation of the publication candidate

Validated locally on 2026-11-16 using synthetic data, temporary credentials/stores and isolated containers. See [engineering review](engineering-review.md) for findings and [development](development.md) to reproduce the checks.

| Area | Evidence |
| --- | --- |
| Python dependencies | Hash-verified runtime/dev locks; pip check passes; pip-audit reports no known vulnerabilities |
| Python tests | **125 passed** with isolated MySQL, no warnings |
| Container integration | Hardened MySQL and dashboard build; generated schemas/roles, authentication and synthetic create/read/delete verified; encrypted synthetic MySQL restore matches schema/data and rejects ciphertext tampering |
| Android | **24 passed**, assembleDebug passes, strict checksums pass; lint 0 errors / 19 warnings |
| Browser host adapter | **4 Node tests passed** |
| Chromium UI | Five views, refresh, initial/delayed data, inert imported HTML, 390px and 1280px layout checks pass |
| Static/type checks | Ruff check and format pass; strict mypy on publication/build-boundary scripts passes |
| Python coverage | 81.8% statements, 72.1% branches, 79.3% combined, including instrumented subprocesses |
| Vulnerability inventory | Python/Android locks clean; zero HIGH/CRITICAL matches in the patched Alpine dashboard and MySQL candidates; lower-severity MySQL matches remain in [security status](security-status.md) |
| Publication hygiene | Indexed source-only allowlist, common credential/private-path scans, reviewable full-content diff and SHA-256 manifest |

The full Python stack requires Python >=3.12. Local execution covered macOS ARM64/Python 3.13 and Linux ARM64/Python 3.12 container runtime. CI is configured for Linux/Python 3.12 and 3.13. Android verification used the existing external SDK/JDK and a checksum-pinned Gradle bootstrap; a fresh Linux SDK build remains a CI check.

Physical acceptance completed: matching-signature in-place upgrade on Android 17/API 37; pairing/cursor/queued state preserved; all requested health permissions granted; actual upload acknowledgments advanced. This establishes a working ingestion path, not fresh wearable export coverage or complete historical correctness.

Not performed: full real sync completion, phone reboot/background lifecycle acceptance, independent fresh-record export checks for each wearable, live hosted tunnel/client acceptance, production migration, private-network changes, load testing, formal standards certification or transitive license certification. Those are tracked in [deployment acceptance](deployment-acceptance.md). No real health data, database, credential, build output or scanner report is included in the source publication list.

See the [release status](release-readiness.md) for outstanding checks. The isolated restore drill verified schema and data consistency for MySQL, SQLite integrity and attachment hashes. Photo restoration and offsite recovery still require a separate check.
