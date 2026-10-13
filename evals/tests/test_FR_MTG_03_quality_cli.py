"""Malformed saved JSON must not overwrite failed evidence into rubric credit."""

import json
import sys

import pytest
from test_FR_MTG_03_meeting_quality import bank
from tilo_evals.meeting_quality import main


@pytest.mark.parametrize(
    "original,replacement",
    [
        ('"summary_score": 4', '"summary_score": 3, "summary_score": 4'),
        (
            '"invented_commitment_ids": []',
            '"invented_commitment_ids": ["ai1"], "invented_commitment_ids": []',
        ),
        ('"basis": "recorded_provider"', '"basis": "unknown", "basis": "recorded_provider"'),
        ('"id": "E-MEET-12"', '"id": "E-MEET-01", "id": "E-MEET-12"'),
        ('"summary_score": 4', '"summary_score": 4, "summary_score": 4'),
    ],
)
def test_FR_MTG_03_cli_duplicate_keys_cannot_erase_failed_evidence(
    tmp_path, monkeypatch, capsys, original, replacement
):
    bundle = tmp_path / "bundle.json"
    content = json.dumps(bank("recorded_provider"))
    assert original in content
    bundle.write_text(content.replace(original, replacement, 1), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["meeting_quality", str(bundle)])
    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report["provider_quality"] == "pending"
    assert report["pending"] == ["bundle unreadable or malformed"]


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_FR_MTG_03_cli_non_json_numbers_are_malformed(tmp_path, monkeypatch, capsys, token):
    bundle = tmp_path / "bundle.json"
    content = json.dumps(bank("recorded_provider"))
    bundle.write_text(content.replace('"summary_score": 4', f'"unused_score": {token}, "summary_score": 4', 1))
    monkeypatch.setattr(sys, "argv", ["meeting_quality", str(bundle)])
    assert main() == 2
    assert json.loads(capsys.readouterr().out)["provider_quality"] == "pending"


@pytest.mark.parametrize("basis,exit_code", [("scripted_fakes", 2), ("recorded_provider", 0)])
def test_FR_MTG_03_cli_valid_json_preserves_basis(tmp_path, monkeypatch, capsys, basis, exit_code):
    # Hypothetical labels test CLI mechanics only, never actual provider capture.
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps(bank(basis)), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["meeting_quality", str(bundle)])
    assert main() == exit_code
    report = json.loads(capsys.readouterr().out)
    assert report["mechanics"] == "pass"
    assert report["provider_quality"] == ("pending" if basis == "scripted_fakes" else "pass")
