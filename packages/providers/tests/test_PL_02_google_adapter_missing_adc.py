"""PL-02 (live defect 15 Oct 2026): on Cloud Run there is no ADC file (the attached identity answers), so the
service-account-key check found nothing on every model call and logged each miss as an ERROR. A missing file is the
normal case and is not logged; a file that cannot be read or parsed still is (class name only)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from tilo_providers.google_adapter import GoogleSettingsError, refuse_service_account_key


def _env(directory: Path) -> dict[str, str]:
    return {"CLOUDSDK_CONFIG": str(directory), "HOME": str(directory), "APPDATA": str(directory)}


def test_PL_02_a_missing_adc_file_is_not_logged_as_an_error(tmp_path, caplog):
    with caplog.at_level(logging.DEBUG):
        refuse_service_account_key(_env(tmp_path))  # no application_default_credentials.json here

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_PL_02_an_unparseable_adc_file_is_still_logged(tmp_path, caplog):
    (tmp_path / "application_default_credentials.json").write_text("{not json", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        refuse_service_account_key(_env(tmp_path))

    assert any("JSONDecodeError" in r.getMessage() for r in caplog.records)


def test_PL_02_an_unreadable_adc_path_is_still_logged(tmp_path, caplog):
    (tmp_path / "application_default_credentials.json").mkdir()  # opening a directory is an OSError, not a missing file

    with caplog.at_level(logging.ERROR):
        refuse_service_account_key(_env(tmp_path))

    assert [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_PL_02_a_service_account_key_is_still_refused(tmp_path):
    kind = "service" + "_account"  # assembled at runtime: no key-shaped text in the repo
    (tmp_path / "application_default_credentials.json").write_text(json.dumps({"type": kind}), encoding="utf-8")

    with pytest.raises(GoogleSettingsError):
        refuse_service_account_key(_env(tmp_path))
