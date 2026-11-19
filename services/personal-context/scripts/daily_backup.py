import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from context_service.storage import ROOT, Store
from context_service.admin import backup

if __name__ == "__main__":
    print(
        json.dumps(
            backup(
                Store(
                    json.loads((ROOT / "config/runtime.json").read_text())["data_dir"]
                ),
                ROOT
                / "backups"
                / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ"),
            )
        )
    )
