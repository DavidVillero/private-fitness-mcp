"""Portable local launcher. Run with the checkout's virtualenv Python."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "service",
        choices=[
            "fitness",
            "fitness-mcp",
            "ingest",
            "context",
            "context-mcp",
            "combined-mcp",
            "dashboard-mcp",
            "reports",
            "context-backup",
        ],
    )
    args, extra = parser.parse_known_args()
    os.umask(0o077)
    env = dict(os.environ)
    settings = ROOT / "deploy/runtime.local.json"
    if settings.exists():
        for key, value in json.loads(settings.read_text()).items():
            if key not in {"FITNESS_TIMEZONE"} or not isinstance(value, str):
                raise SystemExit("Unsupported local launch setting")
            env.setdefault(key, value)
    env.setdefault("FITNESS_TIMEZONE", "UTC")
    fitness = ROOT / "services/private-fitness-mcp"
    context = ROOT / "services/personal-context"
    commands = {
        "fitness": (fitness, ["-m", "fitness"]),
        "fitness-mcp": (fitness, ["-m", "fitness", "mcp"]),
        "ingest": (fitness, ["-m", "fitness.service", "--loopback-port", "8765"]),
        "context": (context, ["-m", "context_service.server"]),
        "context-mcp": (context, ["-m", "context_service.mcp"]),
        "combined-mcp": (context, ["-m", "context_service.mcp", "--combined"]),
        "dashboard-mcp": (
            ROOT,
            [
                str(ROOT / "services/chatgpt-mcp/dashboard.py"),
                "--context-root",
                str(context),
            ],
        ),
        "reports": (fitness, ["scripts/jobs.py"]),
        "context-backup": (context, ["scripts/daily_backup.py"]),
    }
    directory, command = commands[args.service]
    os.chdir(directory)
    os.execve(sys.executable, [sys.executable, *command, *extra], env)


if __name__ == "__main__":
    main()
