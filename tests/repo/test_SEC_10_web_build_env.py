"""SEC-10: `scripts/web_build_env.py` hands the deploy build the Firebase web config without writing it anywhere.

Static and offline: the sdkconfig text is made up (the key is assembled at runtime), no firebase CLI runs.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest


@pytest.fixture(scope="module")
def script(repo_root: pathlib.Path):
    path = repo_root / "scripts" / "web_build_env.py"
    spec = importlib.util.spec_from_file_location("web_build_env", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sdkconfig(key: str) -> str:
    # The shape `firebase apps:sdkconfig WEB <id>` prints: a comment header, then the config object.
    return (
        "// Copy and paste this into your JavaScript code to initialize the Firebase SDK.\n"
        "firebase.initializeApp({\n"
        '  "projectId": "demo-tilo-web",\n'
        '  "appId": "1:1:web:abc",\n'
        f'  "apiKey": "{key}",\n'
        '  "authDomain": "demo-tilo-web.firebaseapp.com"\n'
        "});\n"
    )


def test_SEC_10_the_sdkconfig_output_gives_the_two_build_variables(script) -> None:
    key = "-".join(["fake", "web", "key", "1"])
    assert script.parse_sdkconfig(_sdkconfig(key)) == {
        "VITE_FIREBASE_API_KEY": key,
        "VITE_FIREBASE_PROJECT_ID": "demo-tilo-web",
    }


def test_SEC_10_unreadable_output_gives_nothing(script) -> None:
    for text in ("", "Error: not logged in", '{"status": "error"}'):
        assert script.parse_sdkconfig(text) == {}


def test_SEC_10_the_build_never_gets_an_api_origin_and_keeps_the_rest_of_the_environment(script) -> None:
    env = script.build_env(
        {"PATH": "p", "VITE_TILO_API_URL": "https://example.test"}, {"VITE_FIREBASE_PROJECT_ID": "x"}
    )
    assert env["VITE_TILO_API_URL"] == ""  # the deployed web app stays the fixture world (P0-07c)
    assert env["PATH"] == "p" and env["VITE_FIREBASE_PROJECT_ID"] == "x"


def test_SEC_10_the_script_pins_the_dev_project_and_writes_no_file(repo_root: pathlib.Path) -> None:
    text = (repo_root / "scripts" / "web_build_env.py").read_text(encoding="utf-8")
    assert 'PROJECT = "essential-wares-510320-f0"' in text
    assert "tilo-demo" not in text
    assert not re.search(r"\bopen\(|write_text|write_bytes|\.env\b", text), "the config goes to the build env only"
    assert not re.search(r"AIza[0-9A-Za-z_-]{20,}", text)
