"""Stop / SubagentStop hook: format, lint and run affected tests before a session ends (PRD 20.4).

Runs `just check-fast` in the session's working directory when there are uncommitted
changes. On failure it blocks the stop once (exit 2) with the tail of the output so the
agent fixes it; it never blocks twice in a row (stop_hook_active), so it cannot loop.
No-ops until the scaffold provides a justfile with a `check-fast` recipe.
"""

import json
import os
import shutil
import subprocess
import sys

TIMEOUT_S = 280


def run(cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_S)


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if event.get("stop_hook_active"):
        sys.exit(0)
    cwd = event.get("cwd") or os.getcwd()
    if not os.path.exists(os.path.join(cwd, "justfile")) or shutil.which("just") is None:
        sys.exit(0)
    listed = run(["just", "--summary"], cwd)
    if "check-fast" not in listed.stdout.split():
        sys.exit(0)
    status = run(["git", "status", "--porcelain"], cwd)
    if status.returncode != 0 or not status.stdout.strip():
        sys.exit(0)
    try:
        result = run(["just", "check-fast"], cwd)
    except subprocess.TimeoutExpired:
        sys.stderr.write("stop_check: `just check-fast` timed out; run it yourself before finishing.\n")
        sys.exit(2)
    if result.returncode != 0:
        tail = (result.stdout + result.stderr)[-3000:]
        sys.stderr.write(f"`just check-fast` failed in {cwd}. Fix before finishing:\n{tail}\n")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
