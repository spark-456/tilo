"""Export a clean copy of one git ref to a folder, for a NEW public repository (SUBMIT-COMPLY).

The owner reviews the exclusion lists before publishing. It never touches a remote,
never changes repository visibility and never pushes. It reads committed files only (git archive), so
untracked local files (agy-bridge/, .env, caches) can never be copied.

    python scripts/export_public.py --ref origin/live15-candidate --target "C:/path/tilo-public" [--list]

Afterwards the owner creates the new public repo on GitHub and runs the git init / commit / push steps
printed at the end (single root commit, noreply author, so none of the 4,000+ internal commits or their
author e-mails become public).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

# Private or internal paths: anything whose posix path starts with / equals one of these is not exported.
EXCLUDE_PREFIXES = (
    ".claude/",  # agent memory, agent prompts, hooks, settings: internal working files
    "agy-bridge/",  # lane notes, handoffs, reports (untracked here, listed for safety)
    "pause/",
    "apps/web/e2e/park/parity/",  # reference needs the excluded design runtime
    "scripts/export_public.py",  # private-repo export tool, not product source
    "tests/repo/test_CX_PUBLIC_SNAPSHOT_export.py",
    ".github/workflows/deploy-dev.yml",  # names the live project; owner decides whether to publish CI at all
    "docs/antigravity-onboarding.md",  # lane prompts with local paths
    "docs/routines-rollout.md",  # local paths
    "docs/lanes.md",
    "docs/parallel-sessions.md",
    "docs/cleanup-ledger.md",
    "docs/p0-07a-notes.md",
    "docs/progress.md",
    "meet-bot/PROGRESS.md",
    "meet-bot/docs/ARCHITECT_BRIEF.md",
    "design_handoff_tilo_web_app/PROMPTS.md",
)
# Claude Design's generated runtime: licence not stated, not Tilo's code (CLAUDE.md: never ported).
EXCLUDE_SUFFIXES = ("/support.js", ".dc.html", "/CLAUDE.md")
EXCLUDE_FILES = {"CLAUDE.md"}

# Mirrors .claude/hooks/guard.py SECRET_PATTERNS plus a few extras. Any hit in an exported file aborts.
SECRET_PATTERNS = [
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"AIza[0-9A-Za-z_\-]{35}",
    r"\bAQ\.[0-9A-Za-z_\-]{40,}",
    r"ya29\.[0-9A-Za-z_\-]{20,}",
    r"1//0[0-9A-Za-z_\-]{30,}",
    r"\bsk-[A-Za-z0-9_\-]{20,}",
    r"\bgh[pousr]_[A-Za-z0-9]{36}\b",
    r"\bnvapi-[A-Za-z0-9_\-]{20,}",
    r"GOCSPX-[A-Za-z0-9_\-]{20,}",
    r'"type"\s*:\s*"service_account"',
]
# Not fatal, printed for the owner to look at.
WARN_PATTERNS = [r"C:[/\\]+Users[/\\]+josna", r"johnregi365", r"sacheevkrish", r"agy-bridge"]

GITIGNORE_ADDITIONS = "\n# Added by export_public.py\n.env\n.env.*\n!.env.example\n"


def excluded(name: str) -> bool:
    return (
        name in EXCLUDE_FILES
        or name == "support.js"
        or name.startswith(EXCLUDE_PREFIXES)
        or name.endswith(EXCLUDE_SUFFIXES)
    )


def sanitize_text(value: str) -> str:
    """Remove machine-specific and private-workflow references from exported text."""
    value = re.sub(r"C:[/\\]+Users[/\\]+[^/\\\s`'\"<>:]+", "<local-home>", value, flags=re.I)
    value = re.sub(r"agy-bridge[/\\]", "<private-workflow>/", value, flags=re.I)
    value = re.sub(r"\.claude[/\\]", "<private-tooling>/", value, flags=re.I)
    return re.sub(r"support\.js", "external-design-runtime", value, flags=re.I)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", default="origin/live15-candidate")
    ap.add_argument("--target", required=True, help="empty or missing folder to export into")
    ap.add_argument("--list", action="store_true", help="print excluded paths and exit without writing")
    args = ap.parse_args()

    target = Path(args.target)
    if not args.list and target.exists() and any(target.iterdir()):
        print(f"refusing: {target} is not empty", file=sys.stderr)
        return 2

    kept = skipped = 0
    fatal: list[str] = []
    warn: dict[str, str] = {}
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tilo-public-stage-", dir=target.parent) as stage_name:
        stage = Path(stage_name)
        proc = subprocess.Popen(["git", "archive", "--format=tar", args.ref], stdout=subprocess.PIPE)
        assert proc.stdout is not None
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                if excluded(member.name):
                    skipped += 1
                    if args.list:
                        print("EXCLUDE", member.name)
                    continue
                data = tar.extractfile(member).read()  # type: ignore[union-attr]
                if b"\x00" not in data[:4096]:
                    original = data.decode("utf-8", "replace")
                    for pat in SECRET_PATTERNS:
                        if re.search(pat, original):
                            fatal.append(f"{member.name}: {pat}")
                    for pat in WARN_PATTERNS:
                        if re.search(pat, original):
                            warn.setdefault(member.name, pat)
                    cleaned = sanitize_text(original)
                    if cleaned != original:
                        data = cleaned.encode("utf-8")
                kept += 1
                if not args.list:
                    out = stage / member.name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(data)
        if proc.wait() != 0:
            print(f"git archive {args.ref} failed", file=sys.stderr)
            return 2
        if fatal:
            print("SECRET-LIKE CONTENT FOUND, fix the source ref and re-run:", file=sys.stderr)
            for line in fatal:
                print("  " + line, file=sys.stderr)
            return 1
        if not args.list:
            with (stage / ".gitignore").open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(GITIGNORE_ADDITIONS)
            if target.exists():
                target.rmdir()  # checked empty at start
            stage.rename(target)
    print(f"kept {kept} files, excluded {skipped}")
    for name, pat in sorted(warn.items()):
        print(f"WARN {name}: matches {pat}")
    if not args.list:
        print(
            "\nNext (owner): create an EMPTY public repo on GitHub, then\n"
            f'  cd "{target}"\n'
            "  git init -b main && git config user.name <name>\n"
            "  git config user.email <id>+<login>@users.noreply.github.com\n"
            '  git add -A && git commit -m "Tilo: Google Cloud AI Builder Cup 2026 submission snapshot"\n'
            "  git remote add origin https://github.com/<owner>/<new-repo>.git && git push -u origin main"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
