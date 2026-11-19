"""Check only Git-indexed publication files; never read runtime data or credentials."""

from pathlib import Path
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {
    "secrets",
    "data",
    "backups",
    ".venv",
    ".gradle",
    "build",
    "node_modules",
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".csv",
    ".jsonl",
    ".apk",
    ".aab",
    ".pem",
    ".key",
    ".jks",
    ".p12",
    ".dump",
    ".zip",
}
PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{32,}"),
    re.compile(r"/Users/[A-Za-z0-9_.-]+/"),
]


def main() -> int:
    names = (
        subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    failures: list[str] = []
    # Standalone service metadata must not silently reintroduce older vulnerable pins.
    pins: dict[str, str] = {}
    for requirements in [
        "requirements.txt",
        "requirements-dev.txt",
    ]:
        for line in (ROOT / requirements).read_text().splitlines():
            if "==" in line and not line.startswith("#"):
                name, version = line.split("==", 1)
                pins[name.lower().replace("_", "-")] = version
    for metadata in ROOT.glob("services/*/pyproject.toml"):
        project = tomllib.loads(metadata.read_text())["project"]
        dependencies = project.get("dependencies", []) + [
            item
            for group in project.get("optional-dependencies", {}).values()
            for item in group
        ]
        for dependency in dependencies:
            match = re.fullmatch(r"([A-Za-z0-9_-]+)(?:\[[^]]+\])?==(.+)", dependency)
            if match:
                name = match[1].lower().replace("_", "-")
                if name in pins and pins[name] != match[2]:
                    failures.append(
                        str(metadata.relative_to(ROOT))
                        + ": dependency pin differs from reviewed root requirements"
                    )
    for name in filter(None, names):
        path = Path(name)
        if (
            FORBIDDEN_PARTS.intersection(path.parts)
            or path.suffix in FORBIDDEN_SUFFIXES
            or path.name == ".env"
            or path.name.endswith(".local.json")
        ):
            failures.append(name + ": runtime/generated file")
            continue
        content = subprocess.check_output(["git", "show", ":" + name], cwd=ROOT)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            failures.append(name + ": binary file")
            continue
        if any(pattern.search(text) for pattern in PATTERNS):
            failures.append(name + ": credential or private-path pattern")
        if (ROOT / name).is_symlink():
            failures.append(name + ": symbolic link")
    if failures:
        print("\n".join(failures))
        return 1
    print(
        "Indexed publication hygiene checks passed; manual content review is still required."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
