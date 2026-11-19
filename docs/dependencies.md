# Dependencies and distribution boundaries

No installed packages, environments, SDK archives, vendor binaries, signed apps, proprietary tunnel executable or credentials are bundled. Dependency declarations refer to external packages; install them in your own environment.

| Layer | Declared dependencies | Distribution note |
| --- | --- | --- |
| Python web/backend | FastAPI, Uvicorn, Pydantic, HTTPX, PyMySQL, cryptography, Pillow, python-multipart | Public open-source packages; exact direct pins in root requirements where specified |
| Tests | pytest, HTTPX, JUnit, JSON-java | Artificial in-code fixtures; no private fixture exports |
| Android | AndroidX Activity, Lifecycle, Health Connect, WorkManager; Kotlin/Gradle tooling | Public build dependencies; SDK/tools supplied by the operator |
| Database | MySQL Community container | Pulled externally; no data volume distributed |
| Browser container | Python Alpine image | Pulled externally; dependencies installed at build time |
| Device sources | Garmin Connect, Zepp, Health Connect | External apps/platform services, not redistributable project source |
| Private networking | Tailscale Serve in documented route | External service/client; not bundled |
| Hosted assistant route | Provider tunnel and account | Optional, provider-specific and not bundled; local stdio works without it |

The vendor apps/accounts and platform SDKs retain their own terms. This inventory is not a transitive license/security audit or a grant to redistribute a vendor component.

Runtime and development Python locks contain exact versions and artifact hashes, resolved for Python >=3.12. Install with `--require-hashes --only-binary=:all:`. macOS ARM64/Python 3.13 and Linux ARM64/Python 3.12 were exercised locally; the checked-in CI matrix targets Linux/Python 3.12 and 3.13. The first GitHub runs were rejected before any job started because of a YAML quoting error in the workflow, which has since been fixed; a passing remote run has not yet been recorded. Other platforms remain unverified.

Dockerfiles pin Python, MySQL and Go image digests. The browser pins its OS security update and removes pip after installation. The MySQL image removes unused mysqlsh with its bundled Python dependencies and rebuilds gosu 1.19.0 with a patched, pinned Go compiler; module downloads use Go's checksum database. Android has a SHA-256-verified Gradle bootstrap, locked resolved libraries and strict artifact verification, including Linux AAPT2. SDK/JDK provisioning is external and is not a bit-for-bit binary reproducibility claim.

See [security status](security-status.md) for vulnerability results and remaining upstream OS advisories. No third-party source, binary, toolchain archive or signed application is redistributed by this repository.

No open-source or other project-code license is granted. See [rights and vendor boundaries](rights-and-vendors.md). Public source visibility does not override third-party licenses or vendor service terms.
