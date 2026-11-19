import argparse
import json
import os
from pathlib import Path
from .database import open_store
from .queries import Queries, TOOLS


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument(
        "--db",
        default=None,
        help="Explicit SQLite path; otherwise use config/database.json",
    )
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("mcp")
    imp = sub.add_parser("import")
    imp.add_argument("file")
    q = sub.add_parser("query")
    q.add_argument("tool", choices=TOOLS)
    q.add_argument("--end-date")
    q.add_argument("--days", type=int, default=7)
    report = sub.add_parser("report")
    report.add_argument("--end-date")
    report.add_argument("--weekly", action="store_true")
    report.add_argument("--output", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--token-file", required=True)
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--tls-cert", required=True)
    s.add_argument("--tls-key", required=True)
    args = p.parse_args()
    store = open_store(args.db, readonly=args.command in ["mcp", "query", "report"])
    if args.command == "init":
        store.initialize()
        print("Database initialized (no measurements).")
    elif args.command == "import":
        raw = Path(args.file).read_bytes()
        if len(raw) > 2_000_000:
            raise SystemExit("File exceeds batch size limit")
        store.initialize()
        print(json.dumps(store.ingest(json.loads(raw))))
    elif args.command == "mcp":
        from .mcp_server import serve

        serve(args.db)
    elif args.command in ["query", "report"]:
        kw = {"days": getattr(args, "days", 7)}
        if args.end_date:
            kw["end_date"] = args.end_date
        tool = (
            args.tool
            if args.command == "query"
            else "get_weekly_fitness_report"
            if args.weekly
            else "get_daily_metrics"
        )
        result = Queries(store).call(tool, kw)
        if args.command == "report" and not args.weekly:
            result = {
                "metrics": result,
                "recovery": Queries(store).call("get_recovery_summary", kw),
            }
        body = json.dumps(result, indent=2, allow_nan=False)
        if args.command == "query":
            print(body)
        else:
            out = Path(args.output)
            out.parent.mkdir(exist_ok=True, parents=True, mode=0o700)
            tmp = out.with_suffix(".tmp")
            tmp.write_text(body + "\n")
            os.chmod(tmp, 0o600)
            tmp.replace(out)
    elif args.command == "serve":
        import uvicorn
        from .api import create_app

        uvicorn.run(
            create_app(args.db, args.token_file),
            host="127.0.0.1",
            port=args.port,
            ssl_certfile=args.tls_cert,
            ssl_keyfile=args.tls_key,
            access_log=False,
        )


if __name__ == "__main__":
    main()
