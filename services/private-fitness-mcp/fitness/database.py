"""Explicit backend selection; absence of configuration retains the SQLite deployment."""

import json
import os
from pathlib import Path
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


class DatabaseUnavailable(RuntimeError):
    """Safe to expose without driver details or health payloads."""


def open_store(sqlite_path=None, *, readonly=False, config_path=None):
    if sqlite_path is not None:
        return Store(sqlite_path)
    path = Path(
        config_path
        or os.environ.get("FITNESS_DB_CONFIG", ROOT / "config/database.json")
    )
    if not path.exists():
        if config_path is not None or "FITNESS_DB_CONFIG" in os.environ:
            raise ValueError("Explicit database configuration does not exist")
        return Store(ROOT / "data/fitness.sqlite")
    cfg = json.loads(path.read_text())
    if cfg.get("backend") == "sqlite":
        return Store(ROOT / cfg["path"])
    if cfg.get("backend") != "mysql":
        raise ValueError("Unknown database backend")
    from .mysql_store import MySQLStore

    return MySQLStore(cfg, readonly=readonly)
