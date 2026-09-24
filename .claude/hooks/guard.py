"""PreToolUse guard for Tilo (runs for the main session and every subagent).

Blocks the tool call (exit 2, reason on stderr) when it would:
- edit a read-only source: docs/prd/, design/source/ (except INDEX.md), design/archive/
- write a .env file, or content that looks like a real secret
- run a shell command that needs the user's sign-off: git push, terraform apply/destroy,
  anything deploying to tilo-demo, LIVE=1 (paid model calls), billing or project creation

Fake secrets for tests must be assembled at runtime, never written as literals.
"""

import json
import re
import sys

READ_ONLY = re.compile(r"(^|/)(docs/prd|design/source|design/archive)/")
READ_ONLY_EXCEPTIONS = re.compile(r"(^|/)design/source/INDEX\.md$")
ENV_FILE = re.compile(r"(^|/)\.env(\.[^/]*)?$")
ENV_EXAMPLE = re.compile(r"(^|/)\.env\.example$")

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

SHELL_RULES = [
    (r"\bgit\s+push\b", "git push needs the user's go-ahead (public-repo decision is pending)"),
    (r"\bterraform\s+(apply|destroy|import)\b", "the user applies infrastructure; produce the plan and commands instead"),
    (r"(?=.*\btilo-demo\b)(?=.*\b(deploy|apply|firebase\s+use|config\s+set\s+project)\b)",
     "anything targeting tilo-demo needs the user's approval"),
    (r"(^|[\s;&|(])LIVE\s*=\s*['\"]?1\b|\$env:LIVE\s*=\s*['\"]?1", "LIVE=1 makes paid model calls; only the user sets it"),
    (r"\bgcloud\s+(beta\s+)?(billing|projects\s+create)\b", "billing and project creation cost money; ask the user"),
]


def block(reason: str) -> None:
    sys.stderr.write(f"Blocked by .claude/hooks/guard.py: {reason}\n")
    sys.exit(2)


def written_text(tool_input: dict) -> str:
    parts = [tool_input.get("content") or "", tool_input.get("new_string") or "", tool_input.get("new_source") or ""]
    for edit in tool_input.get("edits") or []:
        parts.append(edit.get("new_string") or "")
    return "\n".join(parts)


def check_file_tool(tool_input: dict) -> None:
    raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    path = raw.replace("\\", "/")
    if READ_ONLY.search(path) and not READ_ONLY_EXCEPTIONS.search(path):
        block(f"{raw} is read-only (PRD and design exports). Log a question in docs/open-questions.md instead.")
    if ENV_FILE.search(path) and not ENV_EXAMPLE.search(path):
        block(f"{raw}: .env files are never written by agents; use .env.example with placeholders.")
    text = written_text(tool_input)
    for pattern, label in SECRET_PATTERNS:
        if re.search(pattern, text):
            block(f"content written to {raw} looks like {label}. No secrets in code, prompts, logs or fixtures.")


def check_shell_tool(tool_input: dict) -> None:
    command = tool_input.get("command") or ""
    for pattern, reason in SHELL_RULES:
        if re.search(pattern, command, flags=re.IGNORECASE):
            block(reason)


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    tool = event.get("tool_name") or ""
    tool_input = event.get("tool_input") or {}
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        check_file_tool(tool_input)
    elif tool in ("Bash", "PowerShell"):
        check_shell_tool(tool_input)
    sys.exit(0)


if __name__ == "__main__":
    main()
