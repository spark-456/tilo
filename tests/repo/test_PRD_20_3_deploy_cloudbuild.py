"""PRD-20.3 / SEC-02: the dev entry point uses Cloud Build; all calls are faked."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

import pytest


def _run(repo_root: pathlib.Path, tmp_path: pathlib.Path, env_arg: str, *, fail: bool = False):
    assert shutil.which("just"), "just is required to verify the deploy guard"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.txt"
    if sys.platform == "win32":
        (bindir / "gcloud.cmd").write_text(
            '@echo off\r\necho %* >> "%TILO_FAKE_GCLOUD_LOG%"\r\nif "%TILO_FAKE_GCLOUD_FAIL%"=="1" exit /b 7\r\n',
            encoding="utf-8",
        )
    else:
        shim = bindir / "gcloud"
        shim.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$TILO_FAKE_GCLOUD_LOG"\n'
            '[ "$TILO_FAKE_GCLOUD_FAIL" != "1" ] || exit 7\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)
    env = dict(
        os.environ,
        PATH=str(bindir) + os.pathsep + os.environ["PATH"],
        TILO_FAKE_GCLOUD_LOG=str(log),
        TILO_FAKE_GCLOUD_FAIL="1" if fail else "0",
    )
    result = subprocess.run(
        ["just", "--justfile", str(repo_root / "justfile"), "deploy", env_arg],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result, log.read_text(encoding="utf-8").splitlines() if log.exists() else []


@pytest.mark.parametrize("env_arg", ["dev", "env=dev"])
def test_PRD_20_3_deploy_dev_builds_api_then_all_on_the_pinned_dev_project(repo_root, tmp_path, env_arg):
    result, calls = _run(repo_root, tmp_path, env_arg)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 2
    assert "_SERVICE=api" in calls[0] and "_SERVICE=all" in calls[1]
    for call in calls:
        assert "builds submit" in call and "--config cloudbuild.yaml" in call
        assert "--project essential-wares-510320-f0" in call
        assert "--region asia-southeast1" in call
        assert "--gcs-source-staging-dir gs://essential-wares-510320-f0-cloudbuild-staging/source" in call


@pytest.mark.parametrize("env_arg", ["prod", "env=prod", "demo", "dev; echo injected", "dev$(echo injected)"])
def test_SEC_02_deploy_refuses_nondev_before_any_cloud_call(repo_root, tmp_path, env_arg):
    result, calls = _run(repo_root, tmp_path, env_arg)
    assert result.returncode != 0
    assert "only env=dev is allowed here" in result.stderr
    assert calls == []


def test_PRD_20_3_deploy_stops_if_the_api_build_fails(repo_root, tmp_path):
    result, calls = _run(repo_root, tmp_path, "dev", fail=True)
    assert result.returncode != 0
    assert len(calls) == 1 and "_SERVICE=api" in calls[0]
