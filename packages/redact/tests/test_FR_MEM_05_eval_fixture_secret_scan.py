"""FR-MEM-05 acceptance: "Secret scanner over a full eval pass finds 0 tokens or passwords" (and SEC-01's scan of
stores and logs). The replay eval's cases carry no recorded event stream (`recording: null`), so the smallest real
fixture is the live-e2e replay set `evals/bank/live/B-007/model-recordings/*/*.json` (nine recorded model calls).
Each is archived as a `model_call` record with runtime-assembled secrets spliced into its prompt, reply and headers,
and logged through the redacting filter; `scripts/secret_scan.py`'s own `scan_file` then reads every file written.
A control run with an identity redactor must be flagged, so a clean result means something.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from _redact_samples_lib import FIXED_TAIL, REPO_ROOT, SECRET_SCAN, build
from tilo_archive import LocalDirStore, RunArchive
from tilo_redact import RedactingFilter, redact_value

RECORDINGS = sorted((REPO_ROOT / "evals" / "bank" / "live" / "B-007" / "model-recordings").glob("*/*.json"))
SECRETS = [
    build(k, FIXED_TAIL).text for k in ("google_oauth_access", "api_secret_key", "pem_private_key", "nvidia_key")
]
PASSWORD = "Zq" + FIXED_TAIL[:14]


def _taint(recording: dict) -> dict:
    reply = dict(recording["response"], text=f"{recording['response'].get('text')} {SECRETS[0]} {SECRETS[2]}")
    headers = {"Authorization": "Bearer " + FIXED_TAIL[:40]}
    request = {"prompt": f"Use {SECRETS[1]} and {SECRETS[3]}", "headers": headers}
    return {"role": recording["role"], "request": request, "response": reply, "args": {"password": PASSWORD}}


def _run(root, *, redacted: bool) -> list[str]:
    redactor = redact_value if redacted else (lambda payload: payload)
    archive = RunArchive(LocalDirStore(root / "archive"), org_id="org_test01", run_id="r_eval01", redactor=redactor)
    logger = logging.Logger("fr_mem_05_eval", logging.INFO)
    handler = logging.FileHandler(root / "run.log", encoding="utf-8")
    if redacted:
        handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    for path in RECORDINGS:
        payload = _taint(json.loads(path.read_text(encoding="utf-8")))
        archive.append("model_call", payload)
        logger.info("model call %s: %s", path.stem, payload["request"]["prompt"] + payload["response"]["text"])
    handler.close()
    return [str(p) for p in root.rglob("*") if p.is_file()]


def test_FR_MEM_05_the_fixture_exists_and_is_small():
    assert 5 <= len(RECORDINGS) <= 20


def test_FR_MEM_05_secret_scan_over_the_archive_and_log_of_an_eval_fixture_finds_zero(tmp_path):
    files = _run(tmp_path, redacted=True)
    assert len(files) == 2  # one archive file, one log
    assert [f for path in files for f in SECRET_SCAN.scan_file(path)] == []
    written = "".join(Path(p).read_text(encoding="utf-8") for p in files)
    assert PASSWORD not in written and FIXED_TAIL[:40] not in written


def test_FR_MEM_05_the_scan_has_teeth_an_identity_redactor_is_flagged(tmp_path):
    findings = [f for path in _run(tmp_path, redacted=False) for f in SECRET_SCAN.scan_file(path)]
    assert len(findings) >= 4  # google token, sk key, nvidia key and a private key, in the archive and in the log
