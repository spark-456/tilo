"""Local pre-commit hook: reject staged files that look like they contain a
real secret. CLAUDE.md hard rule: "No secrets in code, prompts, logs or
fixtures." Deliberately standalone and self-contained (no imports outside the
stdlib), since pre-commit invokes it directly and it must work as a plain
script.

Patterns mirror the guard hook's SECRET_PATTERNS (kept in sync by hand; the
two are independent by design so neither depends on the other).
"""

from __future__ import annotations

import re
import sys

SECRET_PATTERNS = [
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "a private key"),
    (r"AIza[0-9A-Za-z_\-]{35}", "a Google API key"),
    (r"ya29\.[0-9A-Za-z_\-]{20,}", "a Google OAuth access token"),
    (r"1//0[0-9A-Za-z_\-]{30,}", "a Google OAuth refresh token"),
    (r"\bsk-[A-Za-z0-9_\-]{20,}", "an API secret key"),
    (r"\bgh[pousr]_[A-Za-z0-9]{36}\b", "a GitHub token"),
    (r"\bEAA[A-Za-z0-9]{60,}", "a Meta / WhatsApp access token"),
    (r"\"type\"\s*:\s*\"service_account\"", "a service account key"),
]

COMPILED = [(re.compile(pattern), label) for pattern, label in SECRET_PATTERNS]


def scan_file(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            text = handle.read()
    except OSError:
        return []
    findings = []
    for pattern, label in COMPILED:
        if pattern.search(text):
            findings.append(f"{path}: looks like {label}")
    return findings


def main(argv: list[str]) -> int:
    findings: list[str] = []
    for path in argv:
        findings.extend(scan_file(path))
    if findings:
        sys.stderr.write("secret_scan.py found possible secrets:\n")
        for finding in findings:
            sys.stderr.write(f"  {finding}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
