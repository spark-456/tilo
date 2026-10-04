"""Fixtures for the eval tests (EFF-07); the helpers they import live in _evals_lib.py."""

import pathlib

import pytest
from _evals_lib import write_evals_config


@pytest.fixture
def fake_repo(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """A fake repo root (config/evals.yaml, evals/cases) that the CLI's repo-relative defaults resolve into."""
    write_evals_config(tmp_path / "config")
    (tmp_path / "evals" / "cases").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path
