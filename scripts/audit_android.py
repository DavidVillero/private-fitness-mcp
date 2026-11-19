"""Scan the resolved Android app/test dependency lock, without source or device data."""

from pathlib import Path
import subprocess
import tempfile

SCANNER = "aquasec/trivy:0.69.3@sha256:bcc376de8d77cfe086a917230e818dc9f8528e3c852f7b1aff648949b6258d1c"
ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="pf-android-audit-") as folder:
        work = Path(folder)
        (work / "gradle.lockfile").write_bytes(
            (
                ROOT / "services/private-fitness-mcp/android/app/gradle.lockfile"
            ).read_bytes()
        )
        return subprocess.call(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{work}:/scan:ro",
                SCANNER,
                "fs",
                "--scanners",
                "vuln",
                "--severity",
                "HIGH,CRITICAL",
                "--exit-code",
                "1",
                "/scan",
            ]
        )


if __name__ == "__main__":
    raise SystemExit(main())
