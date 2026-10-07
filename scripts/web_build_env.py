#!/usr/bin/env python3
"""SEC-10: run a web build command with the Firebase web config in its environment (`just deploy-web`).

The web client's App Check needs the Firebase `apiKey` and `projectId` of the `tilo-web` app. They are public
client values, but no key literal is kept in the repository: this script reads them from
`firebase apps:sdkconfig WEB <app id>` (the owner's own `firebase login` is needed) and hands them to the build as
VITE_FIREBASE_API_KEY and VITE_FIREBASE_PROJECT_ID. Nothing is written to disk and nothing is printed. If the
command fails the build still runs without them: App Check is then skipped in the browser (docs/deploy-dev.md).
VITE_TILO_API_URL is always set empty, so the deployed web app stays the fixture / replay world (P0-07c).

Usage: python scripts/web_build_env.py <build command...>   (stdlib only; runs on Windows and Linux)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from typing import Any

APP_ID = "1:379216745263:web:8cda5846cf882c2cefc7da"  # Firebase web app "tilo-web" (infra/ACCESS.md section 7)
PROJECT = "essential-wares-510320-f0"  # the tilo-dev project, pinned like `just deploy-web`

_FIELDS = (("apiKey", "VITE_FIREBASE_API_KEY"), ("projectId", "VITE_FIREBASE_PROJECT_ID"))


def parse_sdkconfig(text: str) -> dict[str, str]:
    """The VITE_ variables found in `firebase apps:sdkconfig` output (JS object text, keys quoted or not)."""
    found: dict[str, str] = {}
    for field, variable in _FIELDS:
        match = re.search(rf"""["']?{field}["']?\s*:\s*["']([^"'\s]+)["']""", text)
        if match:
            found[variable] = match.group(1)
    return found


def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    resolved = shutil.which(argv[0])  # finds pnpm.cmd on Windows
    return subprocess.run([resolved or argv[0], *argv[1:]], text=True, check=False, **kwargs)


def sdk_env() -> dict[str, str]:
    """The Firebase web config for the build; empty (with one line on stderr) when it cannot be read."""
    argv = ["pnpm", "exec", "firebase", "apps:sdkconfig", "WEB", APP_ID, "--project", PROJECT]
    found: dict[str, str] = {}
    try:
        result = _run(argv, capture_output=True, timeout=120)
        if result.returncode == 0:
            found = parse_sdkconfig(result.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    if len(found) != len(_FIELDS):
        print("web_build_env: no Firebase web config (not signed in?); building without App Check.", file=sys.stderr)
        return {}
    return found


def build_env(base: Mapping[str, str], firebase: Mapping[str, str]) -> dict[str, str]:
    return {**base, **firebase, "VITE_TILO_API_URL": ""}


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: web_build_env.py <build command...>", file=sys.stderr)
        return 2
    return _run(argv, env=build_env(os.environ, sdk_env())).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
