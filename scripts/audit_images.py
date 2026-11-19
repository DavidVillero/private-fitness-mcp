"""Scan local container archives without sharing source or mounting the Docker socket.

Reports stay in ignored reports/security. Fail on fixable HIGH/CRITICAL findings;
all unfixed findings remain in the report and require release-owner review.
"""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

SCANNER = "aquasec/trivy:0.69.3@sha256:bcc376de8d77cfe086a917230e818dc9f8528e3c852f7b1aff648949b6258d1c"
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="+")
    args = parser.parse_args()
    reports = ROOT / "reports/security"
    reports.mkdir(parents=True, exist_ok=True)
    failed = False
    with tempfile.TemporaryDirectory(prefix="pf-image-audit-") as folder:
        work = Path(folder)
        for index, image in enumerate(args.images):
            archive = work / "image.tar"
            subprocess.run(["docker", "save", image, "-o", str(archive)], check=True)
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{work}:/scan",
                    SCANNER,
                    "image",
                    "--scanners",
                    "vuln",
                    "--input",
                    "/scan/image.tar",
                    "--format",
                    "json",
                    "--output",
                    "/scan/report.json",
                ],
                check=True,
            )
            report = json.loads((work / "report.json").read_text())
            target = reports / f"image-{index}.json"
            target.write_text(json.dumps(report, indent=2) + "\n")
            vulnerabilities = [
                item
                for result in report.get("Results", [])
                for item in result.get("Vulnerabilities", [])
            ]
            actionable = [
                item
                for item in vulnerabilities
                if item.get("FixedVersion")
                and item.get("Severity") in {"HIGH", "CRITICAL"}
            ]
            unresolved = [
                item
                for item in vulnerabilities
                if not item.get("FixedVersion")
                and item.get("Severity") in {"HIGH", "CRITICAL"}
            ]
            print(
                f"{image}: {len(actionable)} fixable and {len(unresolved)} unfixed HIGH/CRITICAL package/advisory matches; full report {target.relative_to(ROOT)}"
            )
            failed |= bool(actionable)
            archive.unlink()
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
