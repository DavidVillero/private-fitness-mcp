# Development and verification

Supported development targets: Python 3.12/3.13; Linux with Docker Compose or macOS ARM64 with a Docker-compatible engine; JDK 17 and Android SDK 36/build tools 35.0.0. Android minSdk is 34, targetSdk remains 35 pending real-device acceptance of a target-API change. Windows and other Python versions are not verified.

Install into an isolated environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.lock
python -m pip check
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pip_audit -r requirements-dev.lock --no-deps --disable-pip
node --test tests/web/*.test.cjs
python -m playwright install chromium
python scripts/test_browser.py
```

The type gate is intentionally focused on the typed build-bootstrap/publication-boundary scripts. It is not a whole-project type-safety claim. Browser tests use artificial data and a simulated host; they do not connect to a live assistant account. Node's built-in test runner requires Node 20 or later.

For integration tests, start Docker, then run:

```sh
docker build --pull -t private-fitness-check .
python scripts/test_mysql.py --dashboard-image private-fitness-check
python -m coverage report
python scripts/audit_images.py private-fitness-check private-fitness-mysql:local
```

The harness generates new credentials in a temporary directory, creates a random `pf-test-*` Compose project with disposable volumes, exercises dashboard authorization and synthetic CRUD, runs all Python tests against an isolated test schema, and removes only that project's containers/network/volumes in `finally`. It never reads production config. The combined coverage gate is 77%, with subprocess instrumentation; scripts, JS and Android are tested separately. Run `python -m pytest -q` for a quick check without Docker; the MySQL contract will then skip.

Build Android through `services/private-fitness-mcp/scripts/android-build testDebugUnitTest assembleDebug lintDebug`. The bootstrap needs network access for its first verified Gradle archive download. Never commit generated APKs or signing keys.

CI runs Python/static/publication checks, isolated MySQL and browser checks, advisory checks, container builds and Android verification on pushes/PRs and weekly. Action revisions are pinned. Dependabot proposes updates; it cannot replace review or regenerate every lock correctly. After repository creation, require the Verify jobs in branch protection before merging.

## Updating dependencies

Use uv 0.9.11 in an isolated tooling environment to regenerate locks after editing the direct requirement pins:

```sh
uv pip compile requirements.txt --universal --python-version 3.12 --generate-hashes --no-header -o requirements.lock
uv pip compile requirements-dev.txt -c requirements.lock --universal --python-version 3.12 --generate-hashes --no-header -o requirements-dev.lock
```

Install both locks in fresh environments, run all gates, inspect advisory/license changes, and review the diff. For Android, update versions deliberately, regenerate the affected dependency locks and SHA-256 verification metadata from trusted upstream repositories, then rebuild with strict verification. A checksum mismatch is a review event, not a reason to disable verification. Update image digests and OS pins together and rescan both images. Container scans fail for fixable HIGH/CRITICAL matches; unfixed matches stay visible in the report and still require a release decision.

See [release readiness](release-readiness.md) for the latest local acceptance results, branch-protection policy and gates that remain pending. The MySQL harness additionally encrypts a synthetic dump, rejects ciphertext tampering, restores into a separate test schema, and compares the canonical dump. This does not replace a real private backup restoration drill.
