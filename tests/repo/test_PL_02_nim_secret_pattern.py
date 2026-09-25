"""PL-02 (ticket P0-02b): add an NVIDIA NIM API key pattern ("nvapi-" followed
by a long token) to both secret scanners -- scripts/secret_scan.py (the local
pre-commit hook) and .claude/hooks/guard.py (the PreToolUse write guard) --
using the same regex in both, per scripts/secret_scan.py's own docstring:
"Patterns mirror the guard hook's SECRET_PATTERNS ... kept in sync by hand".

CLAUDE.md hard rule: "No secrets in code, prompts, logs or fixtures. Fake
secrets for tests are assembled at runtime." The fake NIM key below is built
from a random suffix at import/call time (`secrets.token_urlsafe`), never
written as a single literal "nvapi-..." string anywhere in this file, so
nothing here is itself a real or fixed fake secret for a scanner (or a future
one) to flag as committed.

Both modules are loaded by file path (not `import scripts.secret_scan` /
`import guard`): scripts/ and .claude/hooks/ are not packages on sys.path for
this test tree, and scripts/secret_scan.py's own contract
(test_PRD_20_3_secret_scan_script_exists) is that it never imports from
.claude, so this test must not make that import happen indirectly either --
each module is loaded independently, exactly as pre-commit and the PreToolUse
hook each run it standalone.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import secrets
import types


def _load_module(path: pathlib.Path, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"could not load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_nim_key() -> str:
    # nvapi- followed by a long random token, assembled at runtime (never a
    # literal), matching the ticket's "nvapi- followed by a long token" shape.
    return "nvapi-" + secrets.token_urlsafe(48)


def test_PL_02_secret_scan_flags_nvidia_nim_key(repo_root, tmp_path):
    module = _load_module(repo_root / "scripts" / "secret_scan.py", "secret_scan_under_test")
    fake_key = _fake_nim_key()
    target = tmp_path / "leaked.txt"
    target.write_text(f"export NVIDIA_API_KEY={fake_key}\n", encoding="utf-8")

    findings = module.scan_file(str(target))

    assert findings, (
        "PL-02: scripts/secret_scan.py must flag an NVIDIA NIM API key (nvapi- followed by a long "
        "token) as a possible secret, but scan_file() found nothing"
    )
    assert any("nvidia" in f.lower() or "nim" in f.lower() for f in findings), (
        f"PL-02: the finding should describe an NVIDIA / NIM key, got: {findings}"
    )


def test_PL_02_guard_hook_secret_patterns_flag_nvidia_nim_key(repo_root):
    module = _load_module(repo_root / ".claude" / "hooks" / "guard.py", "guard_under_test")
    fake_key = _fake_nim_key()
    text = f"export NVIDIA_API_KEY={fake_key}\n"

    matched = any(re.search(pattern, text) for pattern, _label in module.SECRET_PATTERNS)

    assert matched, (
        "PL-02: .claude/hooks/guard.py SECRET_PATTERNS must include an NVIDIA NIM API key pattern "
        "(nvapi- followed by a long token) so PreToolUse blocks writing one, but no pattern matched"
    )


def test_PL_02_nvapi_pattern_is_the_same_regex_in_both_scanners(repo_root):
    # scripts/secret_scan.py's docstring commits to this by hand; assert it
    # actually holds instead of trusting the comment.
    secret_scan = _load_module(repo_root / "scripts" / "secret_scan.py", "secret_scan_under_test_2")
    guard = _load_module(repo_root / ".claude" / "hooks" / "guard.py", "guard_under_test_2")

    def _nvapi_patterns(patterns):
        return [pattern for pattern, label in patterns if "nvapi" in pattern.lower() or "nim" in label.lower()]

    scan_patterns = _nvapi_patterns(secret_scan.SECRET_PATTERNS)
    guard_patterns = _nvapi_patterns(guard.SECRET_PATTERNS)

    assert scan_patterns, "PL-02: scripts/secret_scan.py SECRET_PATTERNS has no nvapi- pattern yet"
    assert guard_patterns, "PL-02: .claude/hooks/guard.py SECRET_PATTERNS has no nvapi- pattern yet"
    assert scan_patterns == guard_patterns, (
        "PL-02: the nvapi- pattern must be the same regex in both scanners "
        f"(scripts/secret_scan.py: {scan_patterns!r}, .claude/hooks/guard.py: {guard_patterns!r})"
    )


def test_PL_02_secret_scan_still_ignores_ordinary_env_var_names(repo_root, tmp_path):
    # Regression guard alongside the new pattern: an ordinary (non-secret-shaped)
    # api_key_env name like the ones this ticket's contract fixtures use must
    # never itself be flagged as a secret.
    module = _load_module(repo_root / "scripts" / "secret_scan.py", "secret_scan_under_test_3")
    target = tmp_path / "config_snippet.txt"
    target.write_text('"api_key_env": "NVIDIA_API_KEY"\n', encoding="utf-8")

    findings = module.scan_file(str(target))

    assert not findings, (
        f"PL-02: an api_key_env *name* (not a value) must never be flagged as a secret, got: {findings}"
    )
