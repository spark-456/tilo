"""FR-CON-04 / FR-CON-05: Gmail and Drive are declared in config/connectors.yaml with least-privilege
scopes (PRD 12.1, 12.2, 16.1). API_FR_CON_04_05.md "Shipped config"."""

from __future__ import annotations

import pathlib

import pytest
import yaml
from _oauth_lib import DRIVE_FILE, GMAIL_COMPOSE, GMAIL_READONLY, GMAIL_SEND

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CONFIG = REPO_ROOT / "config" / "connectors.yaml"
BROAD_GMAIL = {"https://mail.google.com/", "https://www.googleapis.com/auth/gmail.modify"}
BROAD_DRIVE = {"https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/drive.readonly"}


def _registry():
    from tilo_connectors.registry import load_registry

    assert CONFIG.is_file(), "config/connectors.yaml must declare the shipped connectors (PRD 12.1)"
    return load_registry(CONFIG)


def _tiers() -> dict[str, str]:
    return yaml.safe_load((REPO_ROOT / "config" / "autonomy.yaml").read_text(encoding="utf-8"))["actions"]


def test_FR_CON_04_shipped_config_declares_gmail_with_minimal_scopes_per_capability():
    gmail = _registry().get("gmail")
    assert gmail["auth"] == "oauth2"
    assert gmail["scopes"]["read"] == [GMAIL_READONLY]
    assert gmail["scopes"]["search"] == [GMAIL_READONLY]
    assert gmail["scopes"]["write"] == [GMAIL_COMPOSE]
    assert gmail["scopes"]["send"] == [GMAIL_SEND]
    every = {s for scopes in gmail["scopes"].values() for s in scopes}
    assert not every & BROAD_GMAIL, f"broader than needed: {sorted(every & BROAD_GMAIL)}"


def test_FR_CON_04_shipped_gmail_declares_read_search_draft_and_send_actions():
    gmail = _registry().get("gmail")
    by_id = {a["id"]: a for a in gmail["actions"]}
    assert {"read_email", "search_email", "create_draft", "send_email"} <= set(by_id)
    assert by_id["read_email"]["gate_type"] == "none"
    assert by_id["search_email"]["gate_type"] == "none"
    assert by_id["create_draft"]["gate_type"] == "approval"
    assert by_id["send_email"]["gate_type"] == "approval"


def test_FR_CON_05_shipped_config_declares_drive_with_drive_file_only():
    """PRD 12.2: read the files the user picks, write to a Tilo folder; drive.file covers both."""
    drive = _registry().get("google_drive")
    assert drive["auth"] == "oauth2"
    assert {"read", "list", "write"} <= set(drive["capabilities"])
    for capability, scopes in drive["scopes"].items():
        assert scopes == [DRIVE_FILE], f"{capability} must use drive.file only, got {scopes}"
    by_id = {a["id"]: a for a in drive["actions"]}
    assert by_id["read_file"]["capability"] == "read"
    assert by_id["list_files"]["capability"] == "list"
    assert by_id["save_file"]["capability"] == "write"
    assert by_id["save_file"]["gate_type"] == "approval"
    every = {s for scopes in drive["scopes"].values() for s in scopes}
    assert not every & BROAD_DRIVE


@pytest.mark.parametrize("connector", ["gmail", "google_drive"])
def test_FR_CON_04_declared_tiers_equal_the_risk_tier_table(connector):
    """FR-CON-06 consistency: a declared base tier never disagrees with config/autonomy.yaml."""
    tiers = _tiers()
    for action in _registry().get(connector)["actions"]:
        if action["id"] in tiers:
            assert action["risk_tier"] == tiers[action["id"]], action["id"]
