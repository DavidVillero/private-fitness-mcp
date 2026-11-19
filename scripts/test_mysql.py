"""Run the full suite against a disposable MySQL instance; never use a live config.

Only a random pf-test-* Compose project and its temporary volume are removed.
Requires Docker Compose, the project's dev lock, and a loopback socket.
"""

from pathlib import Path
import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]


def smoke_dashboard(base):
    headers = {
        "tailscale-user-login": "owner@example.invalid",
        "origin": "https://fitness.example.invalid:9443",
        "x-hq-request": "1",
        "host": "fitness.example.invalid:9443",
    }

    def request(path, method="GET", body=None, authenticated=True):
        req = urllib.request.Request(
            base + path,
            method=method,
            headers=headers if authenticated else {},
            data=None if body is None else json.dumps(body).encode(),
        )
        if body is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)

    for attempt in range(30):
        try:
            assert request("/healthz", authenticated=False)["status"] == "running"
            break
        except (OSError, AssertionError):
            if attempt == 29:
                raise
            time.sleep(1)
    try:
        request("/api/dashboard", authenticated=False)
        raise AssertionError("Unauthenticated dashboard access")
    except urllib.error.HTTPError as error:
        assert error.code in (400, 401)
    created = request(
        "/api/meals",
        "POST",
        {
            "day": "2020-01-01",
            "description": "Synthetic integration fixture",
            "calories": 100,
        },
    )
    snapshot = request("/api/dashboard?end_date=2020-01-01&days=1")
    assert any(row["id"] == created["id"] for row in snapshot["logs"]["meals"])
    assert request("/api/meals/" + created["id"], "DELETE", {})["deleted"]
    print(
        "Container authentication, generated DB permissions, read/write/delete smoke passed."
    )


def smoke_restore(compose, temp):
    """Encrypt a synthetic dump and restore it into a new, disposable schema."""
    import hashlib
    from cryptography.fernet import Fernet, InvalidToken

    def mysql(statement):
        return subprocess.run(
            compose
            + [
                "exec",
                "-T",
                "mysql",
                "sh",
                "-c",
                'MYSQL_PWD="$(cat /run/secrets/mysql-root)" exec mysql -uroot --batch',
            ],
            input=statement,
            text=True,
            capture_output=True,
            check=True,
        ).stdout

    def dump(schema):
        # Schema names are fixed test-only constants, never operator input.
        assert schema in {"fitness_test", "fitness_restore_test"}
        return subprocess.run(
            compose
            + [
                "exec",
                "-T",
                "mysql",
                "sh",
                "-c",
                'MYSQL_PWD="$(cat /run/secrets/mysql-root)" exec mysqldump -uroot '
                "--single-transaction --no-tablespaces --set-gtid-purged=OFF "
                "--skip-comments --order-by-primary " + schema,
            ],
            capture_output=True,
            check=True,
        ).stdout

    original = dump("fitness_test")
    assert b"INSERT INTO" in original, "Restore drill requires synthetic rows"
    cipher = Fernet(Fernet.generate_key())  # Ephemeral test key, not a backup policy.
    encrypted = temp / "synthetic-dump.enc"
    encrypted.write_bytes(cipher.encrypt(original))
    encrypted.chmod(0o600)
    token = encrypted.read_bytes()
    try:
        cipher.decrypt(token[:-1] + (b"A" if token[-1:] != b"A" else b"B"))
    except InvalidToken:
        pass
    else:
        raise AssertionError("Tampered backup was accepted")
    recovered = cipher.decrypt(token)
    assert hashlib.sha256(recovered).digest() == hashlib.sha256(original).digest()
    # No IF NOT EXISTS: never restore over a pre-existing destination.
    mysql("CREATE DATABASE fitness_restore_test;")
    mysql("USE fitness_restore_test;\n" + recovered.decode())
    assert dump("fitness_restore_test") == original, "Restored schema/data differ"
    print("Synthetic encrypted MySQL restore: schema/data match; tamper rejected.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dashboard-image",
        help="Locally built test image; runs container smoke against the disposable database",
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pf-test-") as folder:
        temp = Path(folder)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/setup_local.py"),
                "--root",
                str(temp),
                "--mysql-port",
                str(port),
            ],
            check=True,
            capture_output=True,
        )
        compose_text = (
            (ROOT / "deploy/compose.yaml")
            .read_text()
            .replace("context: ..", "context: " + json.dumps(str(ROOT)))
        )
        if args.dashboard_image:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                dashboard_port = sock.getsockname()[1]
            # JSON quoting prevents an image argument from injecting YAML.
            compose_text = compose_text.replace(
                "build: ..", "image: " + json.dumps(args.dashboard_image)
            )
            compose_text = compose_text.replace(
                "127.0.0.1:8787:8787", f"127.0.0.1:{dashboard_port}:8787"
            )
        (temp / "deploy/compose.yaml").write_text(compose_text)
        project = "pf-test-" + secrets.token_hex(8)
        compose = [
            "docker",
            "compose",
            "--env-file",
            str(temp / ".env"),
            "-f",
            str(temp / "deploy/compose.yaml"),
            "-p",
            project,
        ]
        try:
            try:
                subprocess.run(
                    compose
                    + [
                        "up",
                        "--build",
                        "-d",
                        "--wait",
                        "--wait-timeout",
                        "180",
                        "mysql",
                    ],
                    check=True,
                )
            except subprocess.CalledProcessError:
                # Disposable test credentials only; surface why the server failed.
                subprocess.run(compose + ["ps", "--all"])
                subprocess.run(
                    compose + ["logs", "--no-color", "--tail", "200", "mysql"]
                )
                raise
            if args.dashboard_image:
                subprocess.run(
                    compose + ["--profile", "dashboard", "up", "-d", "dashboard"],
                    check=True,
                )
                try:
                    smoke_dashboard(f"http://127.0.0.1:{dashboard_port}")
                except Exception:
                    subprocess.run(
                        compose
                        + [
                            "--profile",
                            "dashboard",
                            "logs",
                            "--no-color",
                            "--tail",
                            "100",
                        ]
                    )
                    raise
            sys.path.insert(0, str(ROOT / "services/private-fitness-mcp"))
            from fitness.mysql_store import SCHEMA

            sql = (
                "CREATE DATABASE fitness_test;\nUSE fitness_test;\n"
                + ";\n".join(SCHEMA)
                + ";\n"
            )
            for role in ["reader", "writer"]:
                privileges = "SELECT" if role == "reader" else "SELECT,INSERT,UPDATE"
                for table in ["records", "batches"]:
                    sql += f"GRANT {privileges} ON fitness_test.{table} TO 'fitness_{role}'@'%';\n"
            subprocess.run(
                compose
                + [
                    "exec",
                    "-T",
                    "mysql",
                    "sh",
                    "-c",
                    'MYSQL_PWD="$(cat /run/secrets/mysql-root)" exec mysql -uroot --batch',
                ],
                input=sql,
                text=True,
                check=True,
                capture_output=True,
            )
            config = json.loads(
                (temp / "services/private-fitness-mcp/config/database.json").read_text()
            )
            config["database"] = "fitness_test"
            for role in ["reader", "writer"]:
                config[role]["password_file"] = str(
                    temp
                    / "services/private-fitness-mcp"
                    / config[role]["password_file"]
                )
            config_path = temp / "test.local.json"
            config_path.write_text(json.dumps(config))
            config_path.chmod(0o600)
            env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith(("FITNESS_", "HQ_", "CONTEXT_"))
            }
            env.update(
                COVERAGE_RCFILE=str(ROOT / "pyproject.toml"),
                COVERAGE_FILE=str(ROOT / ".coverage"),
                FITNESS_MYSQL_TEST_CONFIG=str(config_path),
                PYTHONPATH=str(ROOT / "services/private-fitness-mcp"),
            )
            result = subprocess.call(
                [sys.executable, "-m", "coverage", "run", "-m", "pytest", "-q"],
                cwd=ROOT,
                env=env,
            )
            subprocess.run(
                [sys.executable, "-m", "coverage", "combine"], cwd=ROOT, check=True
            )
            if result == 0:
                smoke_restore(compose, temp)
            return result
        finally:
            subprocess.run(
                compose
                + ["--profile", "dashboard", "down", "--volumes", "--remove-orphans"],
                check=True,
            )


if __name__ == "__main__":
    raise SystemExit(main())
