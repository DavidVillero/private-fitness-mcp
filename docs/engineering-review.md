# Software engineering review and remediation

Review/remediation date: 2026-11-16. Scope: the sanitized source candidate, not the running installation or installed phone binary.

## Verdict

**The original engineering findings were remediated in a sanitized candidate. An independent review subsequently identified further data-correctness and proxy-boundary gaps; the follow-up changes below address those gaps. Production sign-off still requires upstream OS review and live deployment acceptance.** This is not an assertion that every possible defect is absent. The review follows themes from [OWASP ASVS](https://asvs.owasp.org/) and [NIST SSDF](https://csrc.nist.gov/Projects/ssdf); it is not a complete standards certification or penetration test.

## Finding disposition

| Original finding | Remediation | Status |
| --- | --- | --- |
| Vulnerable Python pins | Coordinated FastAPI/Starlette upgrade; patched Pillow, multipart, cryptography and test runner; hash-verified locks; decoder allowlist | Fixed; final Python audit has no known matches |
| Oversized multi-record phone queue stalls | Actual UTF-8 byte batching; deterministic split IDs; atomic repair of only the unacknowledged suffix; explicit no-truncation single-record policy | Fixed within documented input limits; seven regression cases |
| Empty/duplicate context capabilities | Reject unsafe token files at startup, distinct scopes, cached capabilities, restart for rotation | Fixed with regression tests |
| Ingestion blocks async event loop | Database transaction runs in worker pool | Fixed; execution-thread regression test |
| Boolean values accepted as integers | Strict schema and activity type validation | Fixed with negative-input tests |
| No repeatable CI/delivery gates | Pinned-action workflow, weekly scans, Dependabot, checked-in disposable MySQL/browser harnesses, static/type/coverage/publication checks | Workflow and local checks implemented |
| Partially reproducible builds | Hashed Python locks, pinned base-image digests, verified Gradle bootstrap, Android artifact checksums and dependency lock | Implemented; not a bit-for-bit build or all-platform guarantee |
| Compressed Python and weak failure-path coverage | Format Python, remove dead imports, enforce Ruff; focused strict typing for boundary scripts; tests for retry, restore, CRUD, socket lifecycle, bad images and host errors | Addressed incrementally; broad refactoring/type coverage is not claimed |
| Hosted dashboard compatibility | MCP Apps plus ChatGPT host adapters; initial/delayed results, cancellation/timeouts, missing recovery data and inert imported HTML | Synthetic host/browser checks pass; actual hosted route remains an acceptance gate |

The phone source is now 0.6.2/versionCode 8. Existing source record IDs and deletion semantics are preserved. Unsupported single records are retained and reported, never silently split into new measurement identities, truncated or discarded. An operator may still need a reviewed reconciliation for a legacy unsupported single-record outbox; see [operations](operations.md).

## Additional dependency findings resolved

Expanding the inventory found vulnerable Android app/test dependencies and unused MySQL tooling. Patched Guava, JSON-java, Protobuf and Netty are locked and checksum-verified. The MySQL image removes unused mysqlsh/embedded Python dependencies and rebuilds its existing privilege helper using patched Go. The browser image applies the available zlib patch and removes its package installer after installation.

See [security status](security-status.md) for final scans. Python and Android inventories have no known advisory matches. Neither built container has fixable HIGH/CRITICAL matches. The superseded Debian dashboard base had **47 unfixed HIGH package/advisory matches**; MySQL retains lower-severity upstream findings. These are not waived or presented as proven unreachable. The replacement Alpine image and remaining MySQL advisories are documented in the [container assessment](container-risk-assessment.md).

## Initial verification (before follow-up fixes)

| Check | Local result |
| --- | --- |
| Python 3.13 suite with fresh MySQL | **121 passed**, no test warnings; generated test resources removed |
| MySQL and dashboard containers | Pinned builds succeed; generated schema/role initialization and authenticated synthetic create/read/delete pass |
| Android | **23 unit tests passed**, debug build and strict dependency verification pass; lint 0 errors, 15 compatibility/style warnings |
| Host adapter | **4 Node tests passed** for both host bridges, response origin, errors, timeouts and cancellation |
| Chromium | All five dashboard views, initial/delayed host results, refresh, inert imported HTML, 390px/1280px layouts pass |
| Python static checks | Ruff check/format pass; focused strict mypy passes |
| Python coverage | **79.8% statements / 70.0% branches; 77.3% combined** with subprocess instrumentation |
| Dependency scans | pip-audit and Android lock scan clean; container residuals documented separately |

Coverage scope is the browser Python app, fitness package, context package and MCP overlay. Formatting expanded previously compressed statement lines, and subprocess measurement was added, so the earlier 81.6%/67.3% baseline is not directly comparable. No exclusions were added to inflate coverage. JS, Android and operational scripts have separate checks. Passing tests are evidence of tested behavior, not a guarantee of vendor connectivity or device scheduling.

Bandit's earlier dynamic-SQL alerts were reviewed: table/field names come from internal allowlists/model definitions and values are bound. Its fixed-loopback URL, retry jitter and operator subprocess alerts were triaged, not automatically dismissed as application vulnerabilities. This does not replace a full security review of every path.

## Independent follow-up (2026-11-16)

A second review found silent partial-source step totals, midnight-boundary totals without per-answer flags, a local trusted-header exposure, expired change tokens, and MCP information-minimization gaps. The query layer selects additive interval totals by greatest observed duration, exposes observed coverage and step exclusions without claiming completeness, performs a 30-day expired-token reread with a persistent missed-deletion warning, limits nutrition-history windows, and omits local attachment paths from MCP tool output. The new `dashboard-private` Unix-socket profile removes host TCP ingress but needs a real Tailscale Serve acceptance test. Changes do not reconstruct missed deletion events or prove complete wearable coverage.

See the [release status](release-readiness.md) for outstanding checks.
