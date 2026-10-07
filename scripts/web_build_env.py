#!/usr/bin/env python3
"""SEC-10: run a web build command with the Firebase web config in its environment (`just deploy-web`).

The web client's App Check needs the Firebase `apiKey` and `projectId` of the `tilo-web` app. The key ends up in the
public JavaScript bundle, so it must be restricted in the Google Cloud console BEFORE it is baked in (to the Firebase
App Check API and to the two Hosting origins; infra/ACCESS.md section 7 and docs/deploy-dev.md). The script therefore
bakes it only when the owner has done that and says so with TILO_BAKE_FIREBASE_KEY=1; otherwise the build runs with
no Firebase config and App Check is skipped in the browser (by design, nothing breaks).

With the flag set, the config is read from `firebase apps:sdkconfig WEB <app id>` (the owner's own `firebase login`
is needed), checked for shape, and handed to the build as VITE_FIREBASE_API_KEY and VITE_FIREBASE_PROJECT_ID.
Nothing is written to disk and nothing is printed. VITE_TILO_API_URL is always set empty, so the deployed web app
stays the fixture / replay world (P0-07c).

Usage: python scripts/web_build_env.py <build command...>   (stdlib only; runs on Windows and Linux)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from typing import Any

APP_ID = "1:379216745263:web:8cda5846cf882c2cefc7da"  # Firebase web app "tilo-web" (infra/ACCESS.md section 7)
PROJECT = "essential-wares-510320-f0"  # the tilo-dev project, pinned like `just deploy-web`
BAKE_FLAG = "TILO_BAKE_FIREBASE_KEY"  # "1" (exactly) once the owner has restricted the browser key

_API_KEY_SHAPE = re.compile(r"^AIza[0-9A-Za-z_-]{35}$")
_FIELDS = (("apiKey", "VITE_FIREBASE_API_KEY"), ("projectId", "VITE_FIREBASE_PROJECT_ID"))


def _config_from_json(text: str) -> dict[str, Any] | None:
    """The config object inside `--json` output (`result.fileContents` is itself JSON text), or None."""
    try:
        data: Any = json.loads(text)
    except ValueError:
        return None
    for _ in range(4):  # unwrap {"result": {"fileContents": "<json>"}} and similar, a few levels at most
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                return None
        elif isinstance(data, dict) and "apiKey" not in data:
            nested = data.get("result", data.get("fileContents"))
            if nested is None:
                return None
            data = nested
        else:
            break
    return data if isinstance(data, dict) else None


def parse_sdkconfig(text: str) -> dict[str, str]:
    """The VITE_ variables in `firebase apps:sdkconfig` output: JSON (preferred) or the JS object text."""
    config = _config_from_json(text)
    found: dict[str, str] = {}
    for field, variable in _FIELDS:
        if config is not None and isinstance(config.get(field), str):
            found[variable] = config[field]
            continue
        match = re.search(rf"""["']?{field}["']?\s*:\s*["']([^"'\s]+)["']""", text)
        if match:
            found[variable] = match.group(1)
    return found


def is_valid(found: Mapping[str, str]) -> bool:
    """True only for a Google browser API key shape and the dev project's own id."""
    return bool(_API_KEY_SHAPE.fullmatch(found.get("VITE_FIREBASE_API_KEY", ""))) and (
        found.get("VITE_FIREBASE_PROJECT_ID") == PROJECT
    )


def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    resolved = shutil.which(argv[0])  # finds pnpm.cmd on Windows
    return subprocess.run([resolved or argv[0], *argv[1:]], text=True, check=False, **kwargs)


def sdk_env(base: Mapping[str, str]) -> dict[str, str]:
    """The Firebase web config for the build; empty (with one line on stderr) when not asked for or not readable."""
    if base.get(BAKE_FLAG) != "1":
        print(
            f"web_build_env: {BAKE_FLAG}=1 is not set; building without App Check (see docs/deploy-dev.md).",
            file=sys.stderr,
        )
        return {}
    argv = [
        "pnpm",
        "exec",
        "firebase",
        "apps:sdkconfig",
        "WEB",
        APP_ID,
        "--project",
        PROJECT,
        "--non-interactive",
        "--json",
    ]
    found: dict[str, str] = {}
    try:
        result = _run(argv, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        if result.returncode == 0:
            found = parse_sdkconfig(result.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    if not is_valid(found):
        print(
            "web_build_env: no valid Firebase web config (not signed in?); building without App Check.", file=sys.stderr
        )
        return {}
    return found


def build_env(base: Mapping[str, str], firebase: Mapping[str, str]) -> dict[str, str]:
    # A VITE_FIREBASE_* value already in the shell is dropped: only the checked config above may reach the bundle.
    kept = {k: v for k, v in base.items() if not k.startswith("VITE_FIREBASE_")}
    return {**kept, **firebase, "VITE_TILO_API_URL": ""}


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: web_build_env.py <build command...>", file=sys.stderr)
        return 2
    return _run(argv, env=build_env(os.environ, sdk_env(os.environ))).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
