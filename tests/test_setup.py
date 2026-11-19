"""Fresh-install validation; private generated files live only in temporary folders."""

import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "setup_local", ROOT / "scripts/setup_local.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_setup_creates_separate_roles_without_records(tmp_path, capsys):
    setup.prepare(tmp_path, 13307)
    fitness = tmp_path / "services/private-fitness-mcp"
    config = json.loads((fitness / "config/database.json").read_text())
    assert config["port"] == 13307
    assert config["reader"]["user"] != config["writer"]["user"]
    sql = (fitness / "secrets/mysql/init.sql").read_text()
    assert "INSERT INTO" not in sql
    assert "GRANT SELECT ON fitness.garmin_workouts" in sql
    assert "GRANT SELECT,INSERT,UPDATE,DELETE ON fitness_hq.meals" in sql
    secrets = list(tmp_path.glob("**/secrets/**/*"))
    values = [
        p.read_text().strip() for p in secrets if p.is_file() and p.suffix != ".sql"
    ]
    output = capsys.readouterr().out
    assert values and all(len(v) >= 32 and v not in output for v in values)
    assert len(values) == len(set(values))
    shared = {"root-password", "init.sql"}
    assert all(
        p.stat().st_mode & 0o077 == 0
        for p in secrets
        if p.is_file() and p.name not in shared
    )
    assert all(
        (fitness / "secrets/mysql" / name).stat().st_mode & 0o777 == 0o644
        for name in shared
    )
    # Owner-only directories keep the container-readable files private on the host.
    for directory in [fitness / "secrets", fitness / "secrets/mysql"]:
        assert directory.stat().st_mode & 0o777 == 0o700
    assert not list(tmp_path.glob("**/*.sqlite"))
    with pytest.raises(SystemExit):
        setup.prepare(tmp_path, 13307)


def test_setup_does_not_overwrite_existing_config(tmp_path):
    config = tmp_path / "services/private-fitness-mcp/config/database.json"
    config.parent.mkdir(parents=True)
    config.write_text("existing")
    with pytest.raises(SystemExit):
        setup.prepare(tmp_path, 13307)
    assert config.read_text() == "existing"
    assert not (tmp_path / "services/private-fitness-mcp/secrets").exists()
