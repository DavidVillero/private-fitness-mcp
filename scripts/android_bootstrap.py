"""Download only the official, checksum-pinned Gradle distribution outside the repo."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

VERSION = "8.11.1"
SHA256 = "f397b287023acdba1e9f6fc5ea72d22dd63669d59ed4a289a29b1a76eee151c6"
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if not os.environ.get("JAVA_HOME") or not os.environ.get("ANDROID_HOME"):
        raise SystemExit("Set JAVA_HOME (JDK 17) and ANDROID_HOME (Android SDK).")
    cache = (
        Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
        / "private-fitness"
    )
    cache.mkdir(parents=True, exist_ok=True)
    # Verify the archive on every invocation; never trust a cached executable alone.
    archive = cache / f"gradle-{VERSION}-bin.zip"
    if not archive.exists():
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as downloaded:
            temporary = Path(downloaded.name)
            try:
                with urllib.request.urlopen(
                    f"https://services.gradle.org/distributions/gradle-{VERSION}-bin.zip",
                    timeout=60,
                ) as response:
                    shutil.copyfileobj(response, downloaded)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        with temporary.open("rb") as stream:
            valid = hashlib.file_digest(stream, "sha256").hexdigest() == SHA256
        if not valid:
            temporary.unlink()
            raise SystemExit("Gradle checksum mismatch; download rejected.")
        temporary.replace(archive)
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != SHA256:
            raise SystemExit("Gradle checksum mismatch; cached archive rejected.")
    with tempfile.TemporaryDirectory(prefix="gradle-", dir=cache) as work:
        with zipfile.ZipFile(archive) as distribution:
            for item in distribution.infolist():
                target = (Path(work) / item.filename).resolve()
                if not target.is_relative_to(Path(work).resolve()):
                    raise SystemExit("Unsafe archive member")
            distribution.extractall(work)
        executable = Path(work) / f"gradle-{VERSION}/bin/gradle"
        executable.chmod(0o700)
        return subprocess.call(
            [
                str(executable),
                "--no-daemon",
                "--console=plain",
                "--dependency-verification=strict",
                "-Pkotlin.compiler.execution.strategy=in-process",
                *sys.argv[1:],
            ],
            cwd=ROOT / "services/private-fitness-mcp/android",
        )


if __name__ == "__main__":
    raise SystemExit(main())
