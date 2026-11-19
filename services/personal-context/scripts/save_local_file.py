"""Explicitly save one user-supplied local file. No directory discovery or URL fetching."""

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from context_service.storage import ROOT
from context_service.mcp import Proxy


def main():
    p = argparse.ArgumentParser()
    p.add_argument("file")
    p.add_argument("--mime-type", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--idempotency-key", required=True)
    p.add_argument("--related-record-id", action="append", default=[])
    args = p.parse_args()
    path = Path(args.file)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
        raise SystemExit("Supply a regular file of at most 20 MB")
    proxy = Proxy(json.loads((ROOT / "config/runtime.json").read_text()), "write")
    response = proxy.request(
        "/call",
        {
            "name": "attach_file_reference",
            "arguments": {
                "idempotency_key": args.idempotency_key,
                "authorization": "user_requested",
                "record": {
                    "title": args.title,
                    "original_filename": path.name,
                    "mime_type": args.mime_type,
                    "content_base64": base64.b64encode(path.read_bytes()).decode(),
                    "related_entities": args.related_record_id,
                    "provenance": {
                        "kind": "user_provided",
                        "source": "Explicit local file upload",
                        "original_reference": str(path.resolve()),
                    },
                },
            },
        },
    )
    if "error" in response:
        raise SystemExit(response["error"])
    r = response["result"]
    print(json.dumps({k: r[k] for k in ["id", "content_hash", "durability"]}))


if __name__ == "__main__":
    main()
