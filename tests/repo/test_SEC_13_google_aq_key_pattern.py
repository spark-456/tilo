"""SEC-13 (dependency and code scanning in CI): both secret scanners --
scripts/secret_scan.py (pre-commit and CI `--all-tracked`) and
.claude/hooks/guard.py (the PreToolUse write guard) -- must recognise the newer
Google AI Studio key format: the literal prefix "AQ." followed by a long run of
URL-safe characters, alongside the older "AIza..." format.

CLAUDE.md hard rule: fake secrets for tests are assembled at runtime. The fake
key below is built by concatenation at call time, never written as a literal.
Both modules are loaded by file path, exactly as pre-commit and the hook run
them standalone (same approach as test_PL_02_nim_secret_pattern.py).
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import types

import pytest


def _load_module(path: pathlib.Path, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"could not load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_aq_key() -> str:
    return "AQ." + "A" * 50


def _near_miss() -> str:
    # The prefix with a short tail: too short to be a key, must not be flagged.
    return "AQ." + "A" * 10


def test_SEC_13_secret_scan_flags_google_aq_key(repo_root, tmp_path):
    module = _load_module(repo_root / "scripts" / "secret_scan.py", "secret_scan_sec13")
    target = tmp_path / "leaked.txt"
    target.write_text(f"GOOGLE_API_KEY={_fake_aq_key()}\n", encoding="utf-8")

    findings = module.scan_file(str(target))

    assert any("google" in f.lower() for f in findings), (
        f"SEC-13: scripts/secret_scan.py must flag an AQ.-format Google API key, got: {findings}"
    )


def test_SEC_13_secret_scan_ignores_short_aq_near_miss(repo_root, tmp_path):
    module = _load_module(repo_root / "scripts" / "secret_scan.py", "secret_scan_sec13_near")
    target = tmp_path / "notes.txt"
    target.write_text(f"see {_near_miss()} for details\n", encoding="utf-8")

    assert module.scan_file(str(target)) == [], "SEC-13: a short AQ. string is not a key"


def test_SEC_13_guard_blocks_writing_google_aq_key(repo_root, tmp_path):
    module = _load_module(repo_root / ".claude" / "hooks" / "guard.py", "guard_sec13")
    tool_input = {"file_path": str(tmp_path / "leaked.txt"), "content": f"GOOGLE_API_KEY={_fake_aq_key()}\n"}

    with pytest.raises(SystemExit) as exc:
        module.check_file_tool(tool_input)

    assert exc.value.code == 2, "SEC-13: guard.py must block (exit 2) writing an AQ.-format Google API key"


def test_SEC_13_guard_allows_short_aq_near_miss(repo_root, tmp_path):
    module = _load_module(repo_root / ".claude" / "hooks" / "guard.py", "guard_sec13_near")
    tool_input = {"file_path": str(tmp_path / "notes.txt"), "content": f"see {_near_miss()} for details\n"}

    module.check_file_tool(tool_input)  # returns without exiting


def test_SEC_13_aq_pattern_is_the_same_regex_in_both_scanners(repo_root):
    scan = _load_module(repo_root / "scripts" / "secret_scan.py", "secret_scan_sec13_sync")
    guard = _load_module(repo_root / ".claude" / "hooks" / "guard.py", "guard_sec13_sync")
    key = _fake_aq_key()

    def _aq_patterns(patterns):
        return [pattern for pattern, _label in patterns if "AQ" in pattern and re.search(pattern, key)]

    assert _aq_patterns(scan.SECRET_PATTERNS), "SEC-13: scripts/secret_scan.py has no AQ. pattern"
    assert _aq_patterns(scan.SECRET_PATTERNS) == _aq_patterns(guard.SECRET_PATTERNS), (
        "SEC-13: the AQ. pattern must be the same regex in scripts/secret_scan.py and .claude/hooks/guard.py"
    )
