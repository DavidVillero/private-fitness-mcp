"""Provision a separate empty test schema then run synthetic MySQL tests after approval."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fitness.mysql_store import SCHEMA  # noqa: E402 - import from this checkout after path bootstrap


def run():
    os.umask(0o077)
    sql = (
        "CREATE DATABASE fitness_test;\nUSE fitness_test;\n"
        + ";\n".join(SCHEMA)
        + ";\n"
    )
    cfg = json.loads((ROOT / "config/mysql.local.json").read_text())
    for role in ("writer", "reader"):
        privileges = "SELECT,INSERT,UPDATE" if role == "writer" else "SELECT"
        for table in ("records", "batches"):
            sql += (
                f"GRANT {privileges} ON fitness_test.{table} TO 'fitness_{role}'@'%';\n"
            )
    # Root password is read INSIDE the container and reaches mysql only via its
    # environment, never argv/stdout. SQL contains no measurements or passwords.
    command = [
        "docker",
        "compose",
        "--env-file",
        str(ROOT.parents[1] / ".env"),
        "-f",
        str(ROOT.parents[1] / "deploy/compose.yaml"),
        "exec",
        "-T",
        "mysql",
        "sh",
        "-c",
        'MYSQL_PWD="$(cat /run/secrets/mysql-root)" exec mysql -uroot --batch',
    ]
    result = subprocess.run(command, input=sql, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(
            "Test provisioning failed or test schema exists. No existing schema was overwritten."
        )
    cfg["database"] = "fitness_test"
    path = ROOT / "config/automation/mysql-test.json"
    path.parent.mkdir(exist_ok=True, mode=0o700)
    path.write_text(json.dumps(cfg, indent=2) + "\n")
    env = {**os.environ, "FITNESS_MYSQL_TEST_CONFIG": str(path)}
    # Pytest can show assertions containing synthetic values only; no production DB is queried.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_mysql_integration.py"],
        cwd=ROOT,
        env=env,
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--after-approval", action="store_true")
    args = p.parse_args()
    if not args.after_approval:
        raise SystemExit(
            "User approval required to provision and use MySQL credentials."
        )
    run()
