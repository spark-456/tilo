"""SEC-10: `scripts/web_build_env.py` hands the deploy build the Firebase web config without writing it anywhere,
and only once the owner has restricted the browser key (TILO_BAKE_FIREBASE_KEY=1).

Static and offline: the sdkconfig text is made up (the key is assembled at runtime), no firebase CLI runs.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

import pytest

PROJECT = "essential-wares-510320-f0"


@pytest.fixture(scope="module")
def script(repo_root: pathlib.Path):
    path = repo_root / "scripts" / "web_build_env.py"
    spec = importlib.util.spec_from_file_location("web_build_env", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _key(n: str = "a") -> str:
    return "AI" + "za" + (n * 35)[:35]  # a made-up key with the real shape, assembled at runtime


def _js(key: str, project: str = PROJECT) -> str:
    # The shape `firebase apps:sdkconfig WEB <id>` prints: a comment header, then the config object.
    return (
        "// Copy and paste this into your JavaScript code to initialize the Firebase SDK.\n"
        "firebase.initializeApp({\n"
        f'  "projectId": "{project}",\n'
        '  "appId": "1:1:web:abc",\n'
        f'  "apiKey": "{key}"\n'
        "});\n"
    )


def test_SEC_10_the_sdkconfig_output_gives_the_two_build_variables(script) -> None:
    expected = {"VITE_FIREBASE_API_KEY": _key(), "VITE_FIREBASE_PROJECT_ID": PROJECT}
    assert script.parse_sdkconfig(_js(_key())) == expected
    config = json.dumps({"apiKey": _key(), "projectId": PROJECT, "appId": "1:1:web:abc"})
    for wrapped in (config, json.dumps({"status": "success", "result": {"fileContents": config}})):
        assert script.parse_sdkconfig(wrapped) == expected


def test_SEC_10_unreadable_output_gives_nothing(script) -> None:
    for text in ("", "Error: not logged in", '{"status": "error"}'):
        assert script.parse_sdkconfig(text) == {}


def test_SEC_10_only_a_google_key_shape_and_the_dev_project_pass_the_check(script) -> None:
    good = {"VITE_FIREBASE_API_KEY": _key(), "VITE_FIREBASE_PROJECT_ID": PROJECT}
    assert script.is_valid(good)
    assert not script.is_valid({**good, "VITE_FIREBASE_PROJECT_ID": "other-project"})
    assert not script.is_valid({**good, "VITE_FIREBASE_PROJECT_ID": ""})
    for bad in ("", "short", _key() + "x", _key()[:-1], "XIza" + "a" * 35, _key().replace("a", "!", 1)):
        assert not script.is_valid({**good, "VITE_FIREBASE_API_KEY": bad}), bad
    assert not script.is_valid({})


def test_SEC_10_without_the_flag_nothing_is_read_and_the_build_has_no_config(script, monkeypatch) -> None:
    def never(*args, **kwargs):
        raise AssertionError("the firebase CLI must not run without TILO_BAKE_FIREBASE_KEY=1")

    monkeypatch.setattr(script, "_run", never)
    for env in (
        {},
        {script.BAKE_FLAG: ""},
        {script.BAKE_FLAG: "0"},
        {script.BAKE_FLAG: "true"},
        {script.BAKE_FLAG: " 1"},
    ):
        assert script.sdk_env(env) == {}, env


def test_SEC_10_with_the_flag_a_valid_config_is_used_and_an_invalid_one_is_not(script, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)

        class Done:
            returncode = 0
            stdout = _js(answer["key"], answer["project"])

        return Done()

    answer = {"key": _key(), "project": PROJECT}
    monkeypatch.setattr(script, "_run", fake_run)
    env = {script.BAKE_FLAG: "1"}
    assert script.sdk_env(env) == {"VITE_FIREBASE_API_KEY": _key(), "VITE_FIREBASE_PROJECT_ID": PROJECT}
    assert "--non-interactive" in calls[0] and "--json" in calls[0] and PROJECT in calls[0]
    answer["project"] = "other-project"
    assert script.sdk_env(env) == {}
    answer["project"], answer["key"] = PROJECT, "not-a-key"
    assert script.sdk_env(env) == {}


def test_SEC_10_the_build_never_gets_an_api_origin_or_a_stray_firebase_value(script) -> None:
    env = script.build_env(
        {"PATH": "p", "VITE_TILO_API_URL": "https://example.test", "VITE_FIREBASE_API_KEY": "from-the-shell"},
        {"VITE_FIREBASE_PROJECT_ID": "x"},
    )
    assert env["VITE_TILO_API_URL"] == ""  # the deployed web app stays the fixture world (P0-07c)
    assert env["PATH"] == "p" and env["VITE_FIREBASE_PROJECT_ID"] == "x"
    assert "VITE_FIREBASE_API_KEY" not in env  # a value left in the shell cannot reach the bundle unchecked


def test_SEC_10_the_script_pins_the_dev_project_and_writes_no_file(repo_root: pathlib.Path) -> None:
    text = (repo_root / "scripts" / "web_build_env.py").read_text(encoding="utf-8")
    assert f'PROJECT = "{PROJECT}"' in text
    assert "tilo-demo" not in text
    assert not re.search(r"\bopen\(|write_text|write_bytes|\.env\b", text), "the config goes to the build env only"
    assert not re.search(r"AIza[0-9A-Za-z_-]{20,}", text)
