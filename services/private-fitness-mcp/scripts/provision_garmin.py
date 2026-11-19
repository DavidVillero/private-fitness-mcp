"""Idempotent additive MySQL provisioning; no credentials printed or argv secrets."""

import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DDL = """
USE fitness;
CREATE TABLE IF NOT EXISTS garmin_workouts (
 activity_id VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 start_utc VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 synced_at VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 data LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
 raw_payloads LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
 INDEX garmin_workouts_time (start_utc)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS garmin_sync_state (
 id TINYINT PRIMARY KEY,
 data LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL
) ENGINE=InnoDB;
"""


def main():
    os.umask(0o077)
    secret = ROOT / "secrets/mysql/garmin-sync-password"
    if not secret.exists():
        with secret.open("x") as f:
            f.write(secrets.token_hex(32) + "\n")
    secret.chmod(0o600)
    password = secret.read_text().strip()
    if not password or any(c not in "0123456789abcdef" for c in password):
        raise SystemExit("Invalid local sync secret format")
    sql = (
        DDL
        + f"CREATE USER IF NOT EXISTS 'fitness_garmin_sync'@'%' IDENTIFIED BY '{password}';\n"
    )
    for table in ["garmin_workouts", "garmin_sync_state"]:
        sql += f"GRANT SELECT,INSERT,UPDATE ON fitness.{table} TO 'fitness_garmin_sync'@'%';\n"
        sql += f"GRANT SELECT ON fitness.{table} TO 'fitness_reader'@'%';\n"
    result = subprocess.run(
        [
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
            'MYSQL_PWD="$(cat /run/secrets/mysql-root)" exec mysql -uroot',
        ],
        input=sql,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise SystemExit("Garmin migration failed; driver output suppressed")
    print("Additive Garmin tables and minimum runtime grants provisioned.")


if __name__ == "__main__":
    main()
