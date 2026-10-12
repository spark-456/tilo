"""Test-only Cloud Build gate with a conservative, shared INR spend ceiling.

The deployment .gcloudignore stays unchanged. A separate tracked-source archive
includes test inputs while excluding credentials, state and local artifacts.
"""

from __future__ import annotations

import argparse
import fnmatch
import io
import json
import math
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "essential-wares-510320-f0"
REGION = "asia-southeast1"
MACHINE = "E2_HIGHCPU_8"
# Published USD0.0156/min; conservative INR100/USD, doubled for region/overhead.
INR_PER_MINUTE = 3.2
RESERVATION = 32 * INR_PER_MINUTE
STOP_INR = 400
CAP_INR = 500
ROOTS = set(
    ".claude .github apps config contracts design design_handoff_tilo_web_app docs evals infra "
    "meet-bot packages prompts scripts services skills templates tests".split()
)
FILES = set(
    ".dockerignore .editorconfig .env.example .gcloudignore .gitattributes .gitignore "
    ".pre-commit-config.yaml .python-version CLAUDE.md LICENSE README.md biome.json "
    "cloudbuild.yaml cloudbuild.tests.yaml firebase.json firestore.rules firestore.tokens.rules "
    "justfile package.json pnpm-lock.yaml pnpm-workspace.yaml pyproject.toml tsconfig.base.json uv.lock".split()
)
DENIES = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "service-account*.json",
    "*-credentials.json",
    "application_default_credentials.json",
    "client_secret*.json",
    "token*.json",
    "*.tfplan",
    "tfplan",
    "*.tfstate*",
)


def allowed(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return False
    if path.parts[0] not in ROOTS and name not in FILES:
        return False
    if any(p in {".git", "node_modules", ".venv", "__pycache__"} for p in path.parts):
        return False
    if name in {".env.example", "meet-bot/.env.example", "design/tokens.json"}:
        return True
    return not any(fnmatch.fnmatch(path.name, pattern) for pattern in DENIES)


def archive(ref: str, target: Path) -> None:
    raw = subprocess.check_output(["git", "archive", ref], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(raw)) as source, tarfile.open(target, "w:gz") as output:
        tracked = []
        for member in source:
            if member.isfile() and allowed(member.name):
                output.addfile(member, source.extractfile(member))
                tracked.append(member.name)
        manifest = "\0".join(tracked).encode() + b"\0"
        entry = tarfile.TarInfo(".cloud-source-files")
        entry.size = len(manifest)
        output.addfile(entry, io.BytesIO(manifest))


def build_result(result: subprocess.CompletedProcess) -> dict:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        found = re.search(r"/builds/([0-9a-f-]{36})", result.stderr)
        if found is None:
            raise ValueError("build creation/completion unknown") from None
        return json.loads(
            subprocess.check_output(
                [
                    shutil.which("gcloud") or "gcloud",
                    "builds",
                    "describe",
                    found.group(1),
                    "--project",
                    PROJECT,
                    "--region",
                    REGION,
                    "--format=json",
                ],
                cwd=ROOT,
                text=True,
            )
        )


def write_ledger(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Cloud gate spend",
        "",
        "Test-only, E2_HIGHCPU_8, asia-southeast1. STOP/QUESTION at INR400; cap INR500.",
        "Estimate INR3.2/min: published USD0.0156/min x INR100/USD x 2, rounded up.",
        "Source: https://cloud.google.com/build/pricing. Pending/unknown runs reserve INR102.4.",
        "Deployment .gcloudignore unchanged; only filtered, tracked source is uploaded.",
        "",
        "| UTC | Ref | Build/status | Minutes | Estimated INR | Log |",
        "|---|---|---|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['time']} | {row['ref']} | {row.get('id', 'pending')}/{row['status']} "
            f"| {row.get('minutes', 'reserved')} | {row['inr']:.2f} | {row.get('logUrl', '')} |"
        )
    lines += ["", f"Total conservative estimate/reservations: INR{sum(r['inr'] for r in rows):.2f}."]
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ref")
    common = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=ROOT, text=True
        ).strip()
    )
    parser.add_argument("--ledger-dir", type=Path, default=common.parent / "agy-bridge" / "reports")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]*", args.ref):
        parser.error("expected a local Git ref")
    ref = subprocess.check_output(["git", "rev-parse", "--verify", args.ref + "^{commit}"], cwd=ROOT, text=True).strip()
    args.ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger = args.ledger_dir / "CLOUD-GATE-SPEND.json"
    lock = args.ledger_dir / "CLOUD-GATE-SPEND.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        rows = json.loads(ledger.read_text()) if ledger.exists() else []
        total = sum(row["inr"] for row in rows)
        if total >= STOP_INR or total + RESERVATION >= STOP_INR or total + RESERVATION > CAP_INR:
            raise RuntimeError("STOP/QUESTION: INR400 spend threshold; no build submitted")
        row = {
            "time": datetime.now(UTC).isoformat(),
            "ref": ref,
            "status": "RESERVED",
            "inr": RESERVATION,
            "machine": MACHINE,
        }
        rows.append(row)
        write_ledger(ledger, rows)
        with tempfile.TemporaryDirectory(prefix="tilo-cloud-gate-") as temporary:
            source = Path(temporary) / "source.tgz"
            archive(ref, source)
            config = Path(temporary) / "cloudbuild.tests.yaml"
            config.write_bytes((ROOT / "cloudbuild.tests.yaml").read_bytes())
            command = [
                shutil.which("gcloud") or "gcloud",
                "builds",
                "submit",
                str(source),
                "--config",
                str(config),
                "--project",
                PROJECT,
                "--region",
                REGION,
                "--gcs-source-staging-dir",
                f"gs://{PROJECT}-cloudbuild-staging/source",
                "--suppress-logs",
                "--format=json",
                "--quiet",
            ]
            print(f"Gate ref={ref} machine={MACHINE}; reserved INR{RESERVATION:.2f}", flush=True)
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        try:
            build = build_result(result)
            if isinstance(build, list):
                build = build[0]
            row.update(id=build["id"], status=build["status"], logUrl=build.get("logUrl", ""))
            start = datetime.fromisoformat(build["startTime"].replace("Z", "+00:00"))
            finish = datetime.fromisoformat(build["finishTime"].replace("Z", "+00:00"))
            minutes = (finish - start).total_seconds() / 60
            row["minutes"] = round(minutes, 3)
            row["inr"] = math.ceil(minutes) * INR_PER_MINUTE
        except (ValueError, KeyError, TypeError, IndexError, subprocess.CalledProcessError, OSError):
            row["status"] = "UNKNOWN" if result.returncode == 0 else "FAILED_OR_UNKNOWN"
            # Never silently refund a build whose creation/completion is unknown.
            (args.ledger_dir / f"cloud-gate-{ref[:12]}-submit.log").write_text(
                result.stdout + result.stderr, encoding="utf-8"
            )
        write_ledger(ledger, rows)
        print(json.dumps(row), flush=True)
        return 0 if result.returncode == 0 and row["status"] == "SUCCESS" else 1
    finally:
        os.close(fd)
        lock.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
