# Security status and remaining upstream advisories

Scan date: 2026-11-16. This is a source-candidate review, not penetration testing or a production approval. Advisory matches are package/version evidence, not proof of exploitability in these services. Counts can include the same advisory against several related packages.

## Completed dependency remediation

The full Python runtime/development lock has **zero known advisory matches** in pip-audit 2.10.1. Direct fixes include FastAPI 0.163.1, Starlette 1.10.0, Pillow 13.0.0, python-multipart 0.0.34, cryptography 50.0.2 and pytest 9.0.3. Image loading selects JPEG/PNG/WebP decoders before opening input. Installer hashes are required.

The Android lock now pins patched Guava, JSON-java, Protobuf and Netty versions for app/test configurations. Strict artifact verification and dependency locks accompany the build. This inventory scan does not audit the Android operating system, SDK or every Gradle plugin implementation.

The dashboard image now uses the digest-pinned official Python 3.12 Alpine 3.24 base with krb5-libs 1.22.3-r0 and zlib 1.4-r0 and removes pip from the runtime. The MySQL derivative removes unused mysqlsh and its bundled Python packages, and rebuilds the existing gosu privilege helper from its pinned upstream 1.19 commit with Go 1.27.3. It retains the official database entrypoint, mysql/mysqldump clients and normal least-privilege initialization.

## Container and Android lock scan

Trivy 0.69.3 scanned the local Linux ARM64 images and resolved Android lock. No source, health data or credentials were uploaded; only public advisory databases/dependencies were downloaded. The image scanner gate fails on fixable HIGH/CRITICAL findings and retains all findings in ignored local reports.

| Inventory | Critical | High | Medium | Low | Unknown | Fixable high/critical |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| dashboard | 0 | 0 | 0 | 0 | 0 | 0 |
| mysql | 0 | 0 | 31 | 0 | 2 | 0 |
| android | 0 | 0 | 0 | 0 | 0 | 0 |

The replacement dashboard image has zero findings in this scan and passed all 125 integration tests. This is local Linux ARM64 evidence; Linux AMD64 and new remote CI are not yet verified. The MySQL image retains lower-severity upstream matches. The running installation has not been redeployed, so this result does not describe its existing image. Recheck advisories before deployment.

The browser deployment is non-root, read-only, drops capabilities and uses `no-new-privileges`. The loopback profile trusts Tailscale Serve identity headers, which another local process could forge. The `dashboard-private` profile uses an owner-only Unix socket with no host TCP listener. The native socket passed local authentication tests. On macOS, the Docker Desktop bind mount failed its permission check, and the standalone Tailscale extension could not connect to the native socket. Verify this route on the target host before deployment.

## Review process

Run the commands in [development](development.md) after every dependency change. Review full report records and their upstream advisory links, not only totals. Python and Android checks reject high-risk version regressions. Weekly CI and Dependabot are configured. New commits require their own passing CI. No automatic merge, deployment or production-data access is configured.

Publication hygiene checks inspect indexed text and reject credentials/private-path patterns, runtime directories, databases and binaries. They complement manual source review; they cannot prove the absence of every possible secret. No project license or transitive license-compliance certification is implied.

The historical Debian baseline assessment and its replacement decision are recorded in [container risk assessment](container-risk-assessment.md).
