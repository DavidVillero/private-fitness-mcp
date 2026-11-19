import json
import logging
import logging.handlers
import os
from .storage import ROOT, Store
from .tools import Service, Fitness
from .api import create_app


def main():
    import uvicorn

    os.umask(0o077)
    config = json.loads((ROOT / "config/runtime.json").read_text())
    store = Store(config["data_dir"])
    store.initialize()
    (ROOT / "logs").mkdir(mode=0o700, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        ROOT / "logs/service.jsonl", maxBytes=2_000_000, backupCount=5
    )
    logger = logging.getLogger("personal_context")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    fitness = (
        Fitness(config["fitness_project"]) if config.get("fitness_project") else None
    )
    uvicorn.run(
        create_app(Service(store, fitness), config["credentials"]),
        host="127.0.0.1",
        port=8776,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
