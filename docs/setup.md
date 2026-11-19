# End-to-end setup for a new installation

All example names, dates, addresses and paths here are dummy values. Run commands from the repository root unless stated otherwise. Do not point this checkout at an existing production volume or copy someone else's configuration.

## 1. Python environment

Use Python 3.12 or 3.13 for the full project, with IANA timezone data. the tested supported Python versions are 3.12 and 3.13. A standard Python distribution works; Anaconda is not required. Docker Engine with Compose is needed for the full MySQL/browser path. On macOS, a Docker-compatible runtime must be running.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.lock
python -m pytest -q
```

Use `requirements.lock` with the same hash/binary-only flags for a runtime-only environment (the direct Garmin sync adapter is not included). `requirements-dev.lock` adds tests, static checks and browser tooling. See [development](development.md) for the complete verification commands.

## 2. Generate private local configuration

```sh
python scripts/setup_local.py
```

This generates random, distinct secrets locally and refuses to overwrite an existing setup. It creates `services/private-fitness-mcp/secrets/`, private database config, context read/write tokens and runtime config, `deploy/runtime.local.json`, an ignored root `.env`, and a private dashboard state directory. It starts no process and imports no records. The generated `init.sql` contains credentials and must remain private.

Edit `.env` locally: set `HQ_OWNER` to your own private-network login and `HQ_ORIGIN` to your own private HTTPS dashboard origin. The shipped `owner@example.invalid` and `https://fitness.example.invalid:9443` are intentionally unusable dummy values. Set the same IANA timezone in `.env` and `deploy/runtime.local.json`; both default to UTC. Restart affected processes after changing it. The root `.env` is for Compose; host launchers read `deploy/runtime.local.json`.

MySQL defaults to loopback port **13307**, intentionally separate from common existing installations. Use `python scripts/setup_local.py --mysql-port 13308` on a fresh checkout if needed. That option updates both generated config and `.env`.

## 3. Start the empty database

```sh
docker compose --env-file .env -f deploy/compose.yaml up --build -d --wait mysql
```

The new Compose project is `private-fitness-example`. Its fresh named volume holds `fitness` and `fitness_hq`. Initialization creates empty wearable, batch, Garmin-cache, and manual-log tables. The context database remains a separate SQLite store.

Runtime SQL roles are separated: wearable writer can SELECT/INSERT/UPDATE wearable records and receipts; reader can SELECT wearable and Garmin tables; Garmin writer can SELECT/INSERT/UPDATE only its cache/state tables; browser log writer can SELECT/INSERT/UPDATE/DELETE only manual-log tables. Application roles have no DDL privileges. Root is used by initialization only.

Never reuse an old volume with newly generated passwords. Image initialization SQL runs only for an empty MySQL data directory. The Dockerfiles pin base-image digests. The MySQL derivative removes unused mysqlsh/Python tooling and rebuilds the existing gosu helper with patched Go. The standard mysql/mysqldump clients and official entrypoint remain available. Review [security status](security-status.md) before deployment.

## 4. Run the host services

In separate terminals, from the checkout root:

```sh
scripts/run ingest
```

```sh
scripts/run context
```

Ingestion listens on `127.0.0.1:8765`; context listens on `127.0.0.1:8776`. Neither is published by Compose. Ingestion requires the generated phone token. Context uses separate read/write capabilities and rejects browser origins. The context service initializes an empty local SQLite database on first start. Do not forward its HTTP port to the phone or internet.

The ingestion module also supports an owner-only Unix-domain socket when invoked directly as `python -m fitness.service` from its service directory. The portable launcher uses loopback for the private HTTPS proxy path.

## 5. Private HTTPS and the phone

Install and sign in to your own private-network tooling on the host and phone. The supplied route uses Tailscale Serve and its TLS/identity integration. Inspect existing routes first; only add an unused port:

```sh
tailscale serve status
tailscale serve --bg --https=8443 http://127.0.0.1:8765
```

Use the **actual private HTTPS hostname produced by your installation**, with `/v1/ingest`, when pairing. The dummy `https://fitness.example.invalid:8443/v1/ingest` cannot be used. Do not enable public Funnel. The Android client requires HTTPS with a trusted certificate, rejects redirects, and checks that all resolved addresses are private. [Tailscale Serve documentation](https://tailscale.com/docs/features/tailscale-serve).

Build and pair the phone using [phone instructions](phone-and-sources.md). No database credential goes to the phone.

## 6. Browser dashboard

On a native Linux Docker host, the **Unix-socket profile** below is a candidate for stronger isolation. **Do not use this bind-mounted socket route with host Tailscale on Docker Desktop for macOS.** The local acceptance check failed at socket chmod with EINVAL; the container did not start listening. The ordinary loopback profile remains for local development and CI. Do not run both profiles against the same manual-log store simultaneously.

On a fresh local setup, the owner-only `data/dashboard/sockets` directory is created with mode `0700`. The `dashboard-private` service listens exclusively on its Unix socket and publishes no host TCP port:

```sh
docker compose --env-file .env -f deploy/compose.yaml --profile dashboard-private up -d --build dashboard-private
```

Tailscale Serve can reverse-proxy an HTTP service through a Unix socket with administrator/root privileges. Inspect your installed Serve CLI syntax and existing routes first; a candidate command (replace with your actual absolute path) is:

```sh
sudo tailscale serve --bg --https=9443 unix:/absolute/path/to/private-fitness/data/dashboard/sockets/fitness-hq.sock
```

**The Docker Desktop macOS bind-mounted route failed local acceptance.** A native host dashboard socket passed synthetic HTTP/authentication tests. A temporary live route with standalone Tailscale 1.104.7 on macOS returned HTTP 502; the network extension reported `connect: operation not permitted`, including for the canonical socket path. The temporary route was removed and persistent routes were preserved. Therefore the native macOS route is also unaccepted on this installation. Do not relax socket permissions or disable sandbox protection to work around it. Use a separately reviewed Linux deployment or evaluate the open-source macOS Tailscale variant during a planned migration; replacing the installed client requires its own connectivity and authentication checks. Verify the actual `tailscale serve status` output, expected identity headers, owner login, denied unauthorized access, and no host TCP listener before relying on it. Use a patched Tailscale release (at least 1.104.4 for the published 2026 Unix-backend security fixes) and never enable Funnel. The socket and its parent directory must remain owner-only. A process running as the same owner can still access the socket, so the Unix boundary does not defend against a fully compromised owner account.

The alternative **loopback-only development profile** is:

After replacing the `.env` owner/origin dummy values:

```sh
docker compose --env-file .env -f deploy/compose.yaml --profile dashboard up -d --build dashboard
tailscale serve --bg --https=9443 http://127.0.0.1:8787
```

The container publishes only to loopback and trusts identity headers supplied by Serve, which removes client-supplied identity headers before setting its own. Only the configured `HQ_ORIGIN` host name is accepted; add loopback names for local troubleshooting with `HQ_EXTRA_HOSTS` (comma-separated), and remove them afterwards. Direct access without the matching identity is rejected. Any process on this host that can reach the loopback port can still forge the identity header, so the host itself is inside the trust boundary. To remove that exposure, run Serve in a Tailscale sidecar that shares the dashboard's network namespace and publish no host port (not exercised in this release). Do not expose port 8787 publicly or put an untrusted proxy in front of it. Serve supplies identity headers for supported user-owned connections; verify your own account/device behavior. [Identity-header behavior](https://tailscale.com/docs/features/tailscale-serve).

Manual logs use `fitness_hq`; photos live under `data/dashboard`. Removing a meal does not delete its photo automatically. These logs are not automatically copied into personal context.


### Native macOS socket candidate

Run the dashboard Python process on the same host as Tailscale, with MySQL still isolated in its container. Use a short owner-only socket directory (Unix socket path lengths are limited). Supply `HQ_SOCKET`, `HQ_STATE`, `HQ_SECRETS_DIR` (containing `reader` and `logs` credential files), `HQ_DB_HOST=127.0.0.1`, the configured `HQ_DB_PORT`, and your private `HQ_OWNER`/`HQ_ORIGIN`. All paths and credentials must belong to the new installation. Start from the checkout using its locked Python environment:

```sh
PYTHONPATH=services/private-fitness-mcp python serve_dashboard_socket.py
```

This process has the host Python environment's security boundary, not Docker's read-only filesystem/capability restrictions. Keep the state, credentials and socket directory owner-only. Do not reuse a running installation's socket or start two writers against its manual-log store. Only after a separate acceptance test should Serve be pointed at this socket; never change existing routes as part of a source test. The synthetic test verifies the native socket, health response, rejection of absent/wrong identities, acceptance of a dummy owner, and restart after shutdown. It does not verify Tailscale identity-header replacement or real database credentials.

## 7. MCP

Configure a client using [MCP setup](mcp-clients.md). Fitness-only stdio needs the database; combined/context/dashboard stdio also needs the context HTTP service. Tool discovery should work with empty tables; readings remain missing.

The generated schema includes empty Garmin workout-cache tables and a write-limited role for a future adapter. No Garmin sync adapter ships with this release; see [phone and sources](phone-and-sources.md).

## Minimal offline alternative

For storage/query exploration without MySQL, initialize an explicit empty SQLite path:

```sh
scripts/run fitness --db /tmp/private-fitness-example.sqlite init
scripts/run fitness --db /tmp/private-fitness-example.sqlite query get_daily_metrics --end-date 2000-01-01
```

This alternative does not provide the MySQL browser or Garmin workout cache. It is not the full deployment.
