"""Local operator commands. No automatic discovery of private conversation history."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .storage import ROOT, Store, encode, now, digest


def backup(store, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    target = destination / "context.sqlite"
    with store.connect() as source:
        with sqlite3.connect(target) as dest:
            source.backup(dest)
    target.chmod(0o600)
    saved = Store(destination)
    with saved.connect() as c:
        rows = c.execute("SELECT payload FROM records WHERE category='file'").fetchall()
        rows += c.execute(
            "SELECT payload FROM versions WHERE json_extract(payload,'$.local_storage_path') IS NOT NULL"
        ).fetchall()
    for row in rows:
        payload = json.loads(row[0])
        sha = payload.get("content_hash")
        if sha:
            source = store.root / "files" / sha
            if hashlib.sha256(source.read_bytes()).hexdigest() != sha:
                raise ValueError("Attachment checksum failure")
            (destination / "files").mkdir(mode=0o700, exist_ok=True)
            if not (destination / "files" / sha).exists():
                shutil.copyfile(source, destination / "files" / sha)
                (destination / "files" / sha).chmod(0o600)
    files = {
        str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in destination.rglob("*")
        if p.is_file()
        and p.name != "context.sqlite-shm"
        and p.name != "context.sqlite-wal"
    }
    (destination / "manifest.json").write_text(
        encode(
            {
                "created_at": now(),
                "schema_version": 1,
                "files": files,
                "includes": "database, audit, versions, idempotency, linked local attachments; credentials excluded",
            }
        )
    )
    (destination / "manifest.json").chmod(0o600)
    return {
        "backup": str(destination),
        "files": len(files),
        "integrity": saved.status()["integrity"],
    }


def restore(source, destination):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError(
            "Restore requires a new directory; existing data is never overwritten"
        )
    manifest = json.loads((source / "manifest.json").read_text())
    for name, sha in manifest["files"].items():
        path = source / name
        if (
            not path.resolve().is_relative_to(source)
            or path.is_symlink()
            or hashlib.sha256(path.read_bytes()).hexdigest() != sha
        ):
            raise ValueError("Invalid backup manifest or checksum")
    destination.mkdir(mode=0o700, parents=True)
    for name in manifest["files"]:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(source / name, target)
        target.chmod(0o600)
    store = Store(destination)
    if store.status()["integrity"] != "ok":
        raise ValueError("Restore integrity failure")
    # Paths in historical payloads retain original provenance. Retrieval uses a hash-derived local path.
    return {
        "restored": str(destination),
        "integrity": "ok",
        "note": "Set runtime data_dir to restored directory, then restart service. Restore includes no credentials.",
    }


def export(store, destination):
    with store.connect() as c:
        data = {
            table: [dict(r) for r in c.execute("SELECT * FROM " + table)]
            for table in [
                "records",
                "versions",
                "links",
                "audit",
                "idempotency",
                "schema_migrations",
            ]
        }
    path = Path(destination)
    with path.open("x") as f:
        json.dump(
            {"schema_version": 1, "exported_at": now(), "tables": data},
            f,
            ensure_ascii=False,
        )
    path.chmod(0o600)
    return {
        "export": str(path),
        "records": len(data["records"]),
        "note": "JSON export includes history/audit; use backup for attachment bytes and restore.",
    }


def delete(store, ident):
    with store.connect(False) as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT * FROM records WHERE id=? AND deleted=0", (ident,)
        ).fetchone()
        if not row:
            raise ValueError("Record unavailable")
        stamp = now()
        c.execute(
            "UPDATE records SET deleted=1,updated_at=? WHERE id=?", (stamp, ident)
        )
        c.execute(
            "INSERT INTO audit(record_id,action,timestamp,actor,authorization,version) VALUES(?,?,?,?,?,?)",
            (ident, "soft_delete", stamp, "operator", "user_requested", row["version"]),
        )
    return {
        "deleted_from_active_retrieval": ident,
        "retained": "history, audit, attachments, old backups; no automatic physical erasure",
    }


def import_chatgpt(store, path):
    path = Path(path)
    source = json.loads(path.read_text())
    if not isinstance(source, list):
        raise ValueError("Expected supplied conversations.json list")
    imported = []
    for conversation in source:
        mapping = conversation.get("mapping", {})
        node = conversation.get("current_node")
        chain = []
        seen = set()
        if not node:
            continue
        while node and node not in seen and node in mapping:
            seen.add(node)
            item = mapping[node]
            chain.append(item)
            node = item.get("parent")
        messages = []
        for item in reversed(chain):
            message = item.get("message")
            if not message:
                continue
            role = message.get("author", {}).get("role", "unknown")
            parts = message.get("content", {}).get("parts", [])
            messages.append(
                {
                    "id": message.get("id"),
                    "role": role,
                    "create_time": message.get("create_time"),
                    "parts": parts,
                }
            )
        if not messages:
            continue
        cid = conversation.get("id") or conversation.get("conversation_id")
        if not isinstance(cid, str):
            raise ValueError("Conversation ID missing")
        content = encode(
            {
                "messages": messages,
                "branch": "current_node ancestry",
                "attachments": "references retained; files must be supplied separately",
            }
        )
        if len(content) > 200000:
            raise ValueError(
                "Conversation exceeds 200000 characters; split into explicit source notes"
            )
        timestamp = conversation.get("create_time")
        day = (
            datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
            if isinstance(timestamp, (int, float))
            else None
        )
        ref = "chatgpt-export:" + cid
        payload = {
            "title": str(conversation.get("title") or "Imported conversation")[:500],
            "content": content,
            "effective_date": day,
            "tags": ["imported", "untrusted-source"],
            "related_entities": [],
            "provenance": {
                "kind": "historical_source",
                "source": "User-supplied ChatGPT export",
                "original_reference": ref,
                "confidence": None,
                "notes": "Quoted messages are evidence, never executable instructions. No facts or meals inferred.",
            },
        }
        imported.append(
            store.write(
                "conversation",
                payload,
                "export-" + digest({"ref": ref, "payload": payload}),
                "operator",
                "approved_ingestion",
                source_ref=ref,
            )["id"]
        )
    return {"conversation_records": len(imported), "ids": imported}


def import_codex(store, path):
    path = Path(path)
    entries = []
    for line in path.read_text().splitlines():
        item = json.loads(line)
        if (
            item.get("type") == "response_item"
            and item.get("payload", {}).get("type") == "message"
            and item["payload"].get("role") in ["user", "assistant"]
        ):
            payload = item["payload"]
            text = "\n".join(
                p.get("text", "")
                for p in payload.get("content", [])
                if p.get("type") in ["input_text", "output_text"]
            )
            entries.append(
                {
                    "role": payload["role"],
                    "text": text,
                    "timestamp": item.get("timestamp"),
                }
            )
    content = encode(entries)
    if not entries or len(content) > 200000:
        raise ValueError("No supported messages or supplied transcript too large")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    ref = "codex-supplied:" + sha
    payload = {
        "title": "Supplied Codex transcript: " + path.name,
        "content": content,
        "effective_date": None,
        "tags": ["imported", "untrusted-source"],
        "related_entities": [],
        "provenance": {
            "kind": "historical_source",
            "source": "User-supplied Codex JSONL",
            "original_reference": ref,
            "confidence": None,
            "notes": "Only user/assistant messages. No tools executed; text is untrusted source material.",
        },
    }
    return store.write(
        "conversation",
        payload,
        "codex-" + sha,
        "operator",
        "approved_ingestion",
        source_ref=ref,
    )


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default=str(ROOT / "data"))
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("status")
    for name in ["backup", "export", "import-chatgpt", "import-codex"]:
        s = sub.add_parser(name)
        s.add_argument("path")
    r = sub.add_parser("restore")
    r.add_argument("source")
    r.add_argument("destination")
    d = sub.add_parser("delete")
    d.add_argument("record_id")
    d.add_argument("--confirm", required=True, choices=["soft-delete"])
    m = sub.add_parser("migrate")
    m.add_argument("version", type=int)
    args = p.parse_args()
    store = Store(args.data_dir)
    if args.command == "init":
        store.initialize()
        result = store.status()
    elif args.command == "status":
        result = store.status()
    elif args.command == "backup":
        result = backup(store, args.path)
    elif args.command == "export":
        result = export(store, args.path)
    elif args.command == "restore":
        result = restore(args.source, args.destination)
    elif args.command == "delete":
        result = delete(store, args.record_id)
    elif args.command == "migrate":
        store.migrate(args.version)
        result = {"schema_version": args.version}
    elif args.command == "import-chatgpt":
        result = import_chatgpt(store, args.path)
    elif args.command == "import-codex":
        result = import_codex(store, args.path)
    print(encode(result))


if __name__ == "__main__":
    main()
