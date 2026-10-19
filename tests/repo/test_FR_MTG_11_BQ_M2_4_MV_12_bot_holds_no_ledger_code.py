"""ADR-0042 MV-12 (BQ-M2-4): the meeting bot holds no ledger credential and imports no ledger or API code. It meters its
Live voice through tilo-api's two routes (`meet-bot/bot/voice_meter.py`), over plain HTTP; so no Firestore client, no
`tilo_api`, no harness or ledger module appears in `meet-bot/bot/`, and the bot's new module imports no vendor SDK."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOT = ROOT / "meet-bot" / "bot"
FORBIDDEN = ("tilo_api", "tilo_harness", "firebase_admin", "google.cloud.firestore", "google.cloud.datastore")


def imports(path: Path) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            found.append(node.module or "")
            found += [f"{node.module}.{a.name}" for a in node.names]
    return found


def test_FR_MTG_11_BQ_M2_4_MV_12_no_bot_module_imports_a_ledger_the_api_or_a_firestore_client():
    problems = [
        f"{path.name}: {name}"
        for path in sorted(BOT.glob("*.py"))
        for name in imports(path)
        if any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN)
    ]
    assert problems == []


def test_FR_MTG_11_BQ_M2_4_MV_12_the_remote_meter_uses_http_and_the_contract_only():
    allowed_third_party = {"httpx", "jsonschema", "referencing"}  # HTTP, and the contract's own JSON Schema
    stdlib = {
        "base64",
        "functools",
        "json",
        "logging",
        "pathlib",
        "re",
        "secrets",
        "threading",
        "time",
        "collections",
        "typing",
        "__future__",
    }
    roots = {name.split(".")[0] for name in imports(BOT / "voice_meter.py")}
    assert roots <= allowed_third_party | stdlib, roots - allowed_third_party - stdlib
