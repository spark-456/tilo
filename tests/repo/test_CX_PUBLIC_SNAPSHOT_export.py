"""Public snapshot exclusions and redactions (CX-PUBLIC-SNAPSHOT)."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_public.py"
SPEC = importlib.util.spec_from_file_location("export_public", SCRIPT)
assert SPEC and SPEC.loader
export_public = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export_public)


def test_CX_PUBLIC_SNAPSHOT_excludes_private_and_runtime_files():
    blocked = [
        ".claude/agent-memory/private.md",
        "agy-bridge/inbox/SUPERVISOR.md",
        "pause/notes.md",
        "CLAUDE.md",
        "infra/CLAUDE.md",
        "design/source/support.js",
        "support.js",
        "design/source/Tilo Home.dc.html",
        "apps/web/e2e/park/parity/parity.spec.ts",
        "scripts/export_public.py",
        "tests/repo/test_CX_PUBLIC_SNAPSHOT_export.py",
        "docs/antigravity-onboarding.md",
    ]
    assert all(export_public.excluded(name) for name in blocked)
    assert not export_public.excluded("apps/web/src/main.tsx")
    assert not export_public.excluded("design/source/tilo-world.js")


def test_CX_PUBLIC_SNAPSHOT_redacts_internal_references_in_text():
    source = (
        r"C:\Users\josna\OneDrive\Desktop\Tilo "
        "agy-bridge/reports/check.md .claude/hooks/check.py "
        "design/source/support.js"
    )
    cleaned = export_public.sanitize_text(source)
    for marker in (r"C:\Users", "agy-bridge/", ".claude/", "support.js"):
        assert marker not in cleaned
    assert "<local-home>" in cleaned
