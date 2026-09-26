"""Stop / SubagentStop hook: format, lint and run affected tests before a session ends (PRD 20.4).

Checks only what the session changed: ruff on changed Python files, biome on changed JS/TS/JSON
files, and pytest on the packages those changes live in. Changes to shared inputs (contracts,
config, scripts, root pyproject/lockfile/conftest) run the whole `not emulator` suite.
`.claude/agent-memory/` and `docs/` are not code and never trigger a run. `just check` stays the
full gate before a ticket finishes, and CI runs everything.

On failure it blocks the stop once (exit 2) with the tail of the output so the agent fixes it; it
never blocks twice in a row (stop_hook_active), so it cannot loop.
"""

import json
import os
import shutil
import subprocess
import sys

TIMEOUT_S = 280
IGNORED = (".claude/agent-memory/", "docs/")
FULL_SUITE = ("contracts/", "config/", "scripts/", "packages/contracts-py/", "pyproject.toml", "uv.lock", "conftest.py")
PY_EXT = (".py", ".pyi")
JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".jsonc", ".css")


def run(cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_S)


def changed_paths(cwd: str) -> list[str]:
    status = run(["git", "status", "--porcelain", "-z", "-uall"], cwd)
    if status.returncode != 0:
        return []
    entries = status.stdout.split("\0")
    paths, i = [], 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        if entry[0] in "RC":
            i += 1  # the rename source follows as its own entry
        path = entry[3:]
        if not path.startswith(IGNORED):
            paths.append(path)
    return paths


def pytest_targets(paths: list[str], cwd: str) -> list[str] | None:
    """Directories to hand pytest; None means the whole suite."""
    targets: set[str] = set()
    for path in paths:
        if path.startswith(FULL_SUITE):
            return None
        parts = path.split("/")
        if parts[0] in ("packages", "services") and len(parts) > 2:
            targets.add("/".join(parts[:2]))
        elif parts[0] in ("evals", "skills") and len(parts) > 1:
            targets.add(parts[0])
        elif parts[0] == "tests" and len(parts) > 2:
            targets.add("/".join(parts[:2]))
        elif parts[0] == ".claude" and path.endswith(PY_EXT):
            targets.add("tests/repo")
    return sorted(t for t in targets if os.path.isdir(os.path.join(cwd, t)))


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if event.get("stop_hook_active"):
        sys.exit(0)
    cwd = event.get("cwd") or os.getcwd()
    if not os.path.exists(os.path.join(cwd, "justfile")) or shutil.which("uv") is None:
        sys.exit(0)
    paths = changed_paths(cwd)
    if not paths:
        sys.exit(0)
    existing = [p for p in paths if os.path.isfile(os.path.join(cwd, p))]
    py_files = [p for p in existing if p.endswith(PY_EXT)]
    js_files = [p for p in existing if p.endswith(JS_EXT)]
    steps: list[list[str]] = []
    if py_files:
        steps += [["uv", "run", "ruff", "format", "--check", *py_files], ["uv", "run", "ruff", "check", *py_files]]
    if js_files:
        biome = ["pnpm", "exec", "biome", "check", "--no-errors-on-unmatched", "--files-ignore-unknown=true"]
        steps.append([*biome, *js_files])
    targets = pytest_targets(paths, cwd)
    if targets is None or targets:
        steps.append(["uv", "run", "pytest", "-q", "-m", "not emulator", *(targets or [])])
    for step in steps:
        label = " ".join(step[:4])
        try:
            result = run(step, cwd)
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"stop_check: `{label} ...` timed out; run `just check` before finishing.\n")
            sys.exit(2)
        if result.returncode != 0:
            tail = (result.stdout + result.stderr)[-3000:]
            sys.stderr.write(f"stop_check failed in {cwd} (`{label} ...`). Fix before finishing:\n{tail}\n")
            sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
