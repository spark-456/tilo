"""Lane guard: an Antigravity pull request may change only its lane's paths (docs/lanes.md).

CI runs it on pull requests whose head branch starts with `ag-`:
  python scripts/lane_guard.py --branch <head ref> --base <base ref> [FILE ...]
With no FILE arguments, the changed files are `git diff --name-only --no-renames origin/<base>...HEAD`
(a rename shows as a delete plus an add, so moving a file out of a denied path is caught too).
Branches outside the lanes pass untouched. Exit 1 lists every violation.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

# lane branch prefix -> (the only base it merges into, path prefixes it may change)
LANES: dict[str, tuple[str, tuple[str, ...]]] = {
    "ag-web/": ("phase0-stack", ("apps/web/", "pnpm-lock.yaml", "docs/licences.md")),
    "ag-eval/": ("phase0-stack", ("evals/cases/", "evals/fixtures/", "evals/tests/test_PRD_19_2_")),
    "ag-render/": ("phase0-stack", ("services/render/", "templates/", "uv.lock", "docs/licences.md")),
}
# Never changed by a lane, even under an allowed prefix: Claude-lane seams, generated files, rule files.
DENIED: tuple[str, ...] = (
    "apps/web/src/api/http",
    "apps/web/src/world/registry.generated.ts",
    "apps/web/src/design/tokens.ts",
    "apps/web/src/styles/tokens.css",
    "apps/web/CLAUDE.md",
    "services/render/CLAUDE.md",
)


def violations(branch: str, base: str, files: list[str]) -> list[str]:
    lane = next((prefix for prefix in LANES if branch.startswith(prefix)), None)
    if lane is None:
        # An ag-* branch that names no lane (for example ag-meet/: meet-bot stays with Claude) fails.
        return [f"{branch!r} is not an Antigravity lane ({', '.join(LANES)})"] if branch.startswith("ag-") else []
    lane_base, allowed = LANES[lane]
    name = lane.rstrip("/")
    found = [] if base == lane_base else [f"base is {base!r}; lane {name} merges only into {lane_base!r}"]
    for path in files:
        if path.startswith(DENIED) or not path.startswith(allowed):
            found.append(f"{path}: outside lane {name} (allowed: {', '.join(allowed)})")
    return found


def changed_files(base: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", f"origin/{base}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail when an Antigravity PR leaves its lane's paths.")
    parser.add_argument("--branch", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("files", nargs="*")
    args = parser.parse_args(argv)
    found = violations(args.branch, args.base, args.files or changed_files(args.base))
    for line in found:
        print(f"lane guard: {line}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
