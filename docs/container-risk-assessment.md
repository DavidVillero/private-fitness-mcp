# Container risk assessment — 2026-11-16

Historical baseline: superseded Debian dashboard image, Linux ARM64, current declared Docker/Compose controls. This is a feature-exposure assessment, not exploit testing, a VEX certification, or owner risk acceptance. It does not assess native macOS Python or the host OS.

A fresh Trivy scan reproduced **47 HIGH package/advisory matches across 11 unique CVEs**, zero CRITICAL, and zero fixable HIGH/CRITICAL for the pinned distribution. Dashboard totals remain 92 MEDIUM, 65 LOW, 5 UNKNOWN; MySQL has 31 MEDIUM and 2 UNKNOWN. Full scanner JSON stays in ignored local reports. No finding was suppressed. Debian's tracker identifies affected trixie packages; fixes in unstable do not establish safe compatibility with this image.

| Advisory | Matches | Affected feature and observed exposure | Disposition |
| --- | ---: | --- | --- |
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | 4 | infocmp parser; executable is present, but no dashboard request path invokes it or accepts terminfo input | No identified application trigger; package remains vulnerable |
| [CVE-2026-119373](https://security-tracker.debian.org/tracker/CVE-2026-119373) | 1 | SQLite FTS5 crafted prefix queries; dashboard uses MySQL, no FTS5 queries found in shipped dashboard/fitness paths | No identified dashboard trigger; library remains present |
| [CVE-2026-119374](https://security-tracker.debian.org/tracker/CVE-2026-119374) | 1 | Corrupt SQLite FTS5 index during deletion; dashboard does not accept SQLite uploads | No identified dashboard trigger; do not extend finding to native context service or untrusted backup restoration |
| [CVE-2026-119379](https://security-tracker.debian.org/tracker/CVE-2026-119379) | 1 | SQLite session changeset application; no changeset API usage found | No identified dashboard trigger; library remains present |
| [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | 2 | systemd-homed privilege escalation; systemd-homed executable absent | Affected service absent in this image; no global package suppression |
| [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | 1 | Privileged libacl pathname operations on attacker-controlled paths; no such API found in dashboard | Non-root/capability controls reduce prerequisite access; residual dependency risk |
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642) | 9 | Privileged mount post-hooks; mount is present and setuid, fstab contains no configured entries | Keep no-new-privileges, drop ALL capabilities, non-root; no identified request path |
| CVE-2026-78408 | 9 | nsenter join-cgroup privilege leakage; executable present, no application call path | Scanner advisory reviewed; Debian page unavailable during review. Do not use privileged nsenter against this workload |
| [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409) | 9 | fstab-authorized mount subdirectory traversal; no configured fstab entries | Required privilege/mount setup absent from declared runtime; retain all controls |
| [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | 9 | Restricted bind-mount ownership redirection; no configured fstab entries | Required privilege/mount setup absent from declared runtime; retain all controls |
| [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | 1 | Perl Archive::Tar memory exhaustion; importing Archive::Tar fails because the module is absent | Affected module absent in this image; package match retained |

Evidence: fresh image scan; executable presence checks; /etc/fstab inspection; SQLite 3.46.1; application source searches for FTS5/changesets/process execution; Compose non-root, read-only, cap_drop ALL and no-new-privileges. These observations establish prerequisites and missing call paths only, not proof that future changes cannot expose a vulnerable feature.

## Release decision

The source candidate now replaces this Debian image with digest-pinned Python 3.12 Alpine 3.24, explicitly patched with krb5-libs 1.22.3-r0 and zlib 1.4-r0. A fresh Linux ARM64 Trivy scan reports zero findings, and all 125 integration tests pass against the replacement. No scanner findings were suppressed. The 47 HIGH matches above describe the superseded Debian baseline, not the replacement. MySQL retains 31 MEDIUM and 2 UNKNOWN findings. Verify AMD64 separately. Reassess on dependency changes and before deployment.

The Mac Docker Desktop socket route failed before listening because socket chmod on its bind mount returned EINVAL. Do not waive this permission check. Use the native-host candidate for separate Tailscale acceptance or a reviewed same-VM network design. Container controls described above do not apply to a native host process.
