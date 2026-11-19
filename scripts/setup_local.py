"""Prepare a NEW installation; generate private files, never start services.

No production configuration, credentials, or database is read. Existing generated
files are never overwritten. Use a fresh checkout for a separate installation.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "services/private-fitness-mcp"))
from fitness.mysql_store import SCHEMA  # noqa: E402 - import from this checkout after path bootstrap


def prepare(root, port):
    root = root.resolve()
    fitness = root / "services/private-fitness-mcp"
    context = root / "services/personal-context"
    marker = root / "deploy/runtime.local.json"
    destinations = [
        root / ".env",
        marker,
        fitness / "secrets",
        context / "secrets",
        fitness / "config/database.json",
        fitness / "config/mysql.local.json",
        context / "config/runtime.json",
    ]
    if any(p.exists() or p.is_symlink() for p in destinations):
        raise SystemExit(
            "Local setup already exists; refusing to overwrite or rotate it."
        )
    os.umask(0o077)

    def write(path, value, mode=0o600):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("x") as stream:
            stream.write(value)
        path.chmod(mode)

    # The MySQL entrypoint reads the root password and init SQL as its own
    # container user, not as the operator. On Linux a 0600 bind mount owned by
    # the operator is unreadable there (Docker Desktop on macOS hides this).
    # These two files are world-readable but sit inside owner-only (0700)
    # secrets directories, so other host users still cannot reach them.
    container_readable = 0o644

    def config(path, value):
        write(path, json.dumps(value, indent=2) + "\n")

    passwords = {
        role: secrets.token_hex(32)
        for role in ["root", "writer", "reader", "logs", "garmin-sync"]
    }
    for role, password in passwords.items():
        write(
            fitness / f"secrets/mysql/{role}-password",
            password + "\n",
            container_readable if role == "root" else 0o600,
        )
    write(fitness / "secrets/phone-token", secrets.token_hex(32) + "\n")

    # Import schema definitions only; the provisioner's main function is not run.
    spec = importlib.util.spec_from_file_location(
        "garmin_schema",
        SOURCE / "services/private-fitness-mcp/scripts/provision_garmin.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sql = "USE fitness;\n" + ";\n".join(SCHEMA) + ";\n" + module.DDL
    for role in ["writer", "reader", "garmin-sync"]:
        user = "fitness_garmin_sync" if role == "garmin-sync" else "fitness_" + role
        sql += f"CREATE USER '{user}'@'%' IDENTIFIED BY '{passwords[role]}';\n"
        tables = (
            ["garmin_workouts", "garmin_sync_state"]
            if role == "garmin-sync"
            else ["records", "batches"]
        )
        if role == "reader":
            tables += ["garmin_workouts", "garmin_sync_state"]
        privileges = "SELECT" if role == "reader" else "SELECT,INSERT,UPDATE"
        for table in tables:
            sql += f"GRANT {privileges} ON fitness.{table} TO '{user}'@'%';\n"
    sql += "CREATE DATABASE fitness_hq CHARACTER SET utf8mb4;\nUSE fitness_hq;\n"
    common = "id CHAR(32) PRIMARY KEY, day CHAR(10) NOT NULL, created_utc VARCHAR(40) NOT NULL"
    tables = {
        "meals": common
        + ", description VARCHAR(500) NOT NULL, calories DOUBLE NULL, protein DOUBLE NULL, photo_id CHAR(32) NULL",
        "workouts": common
        + ", category VARCHAR(20) NOT NULL, exercise VARCHAR(200) NOT NULL, sets INT NULL, reps INT NULL, load_kg DOUBLE NULL, minutes DOUBLE NULL, effort INT NULL, notes VARCHAR(1000) NOT NULL",
        "measurements": common
        + ", weight_kg DOUBLE NULL, waist_cm DOUBLE NULL, notes VARCHAR(500) NOT NULL",
    }
    sql += f"CREATE USER 'fitness_hq'@'%' IDENTIFIED BY '{passwords['logs']}';\n"
    for table, fields in tables.items():
        sql += f"CREATE TABLE {table} ({fields}, INDEX day_idx(day)) ENGINE=InnoDB;\n"
        sql += f"GRANT SELECT,INSERT,UPDATE,DELETE ON fitness_hq.{table} TO 'fitness_hq'@'%';\n"
    write(fitness / "secrets/mysql/init.sql", sql, container_readable)
    db = {"backend": "mysql", "host": "127.0.0.1", "port": port, "database": "fitness"}
    for role in ["reader", "writer"]:
        db[role] = {
            "user": "fitness_" + role,
            "password_file": f"secrets/mysql/{role}-password",
        }
    config(fitness / "config/database.json", db)
    config(fitness / "config/mysql.local.json", db)
    credentials = {}
    for scope in ["read", "write"]:
        path = context / f"secrets/{scope}-token"
        write(path, secrets.token_hex(32) + "\n")
        credentials[scope] = str(path)
    config(
        context / "config/runtime.json",
        {
            "url": "http://127.0.0.1:8776",
            "data_dir": str(context / "data"),
            "fitness_project": str(fitness),
            "credentials": credentials,
        },
    )
    (context / "logs").mkdir(parents=True, exist_ok=True, mode=0o700)
    (root / "data/dashboard").mkdir(parents=True, exist_ok=True, mode=0o700)
    (root / "data/dashboard/sockets").mkdir(parents=True, exist_ok=True, mode=0o700)
    config(marker, {"FITNESS_TIMEZONE": "UTC"})
    write(
        root / ".env",
        f"FITNESS_MYSQL_PORT={port}\nFITNESS_TIMEZONE=UTC\nHQ_ORIGIN=https://fitness.example.invalid:9443\nHQ_OWNER=owner@example.invalid\nLOCAL_UID={os.getuid()}\nLOCAL_GID={os.getgid()}\n",
    )
    print(
        "Prepared new local configuration. Secrets were not printed. No services started."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=SOURCE,
        help="New installation destination; used by isolated tests",
    )
    parser.add_argument("--mysql-port", type=int, default=13307)
    args = parser.parse_args()
    if not 1024 <= args.mysql_port <= 65535:
        parser.error("Choose an unprivileged TCP port")
    prepare(args.root, args.mysql_port)
