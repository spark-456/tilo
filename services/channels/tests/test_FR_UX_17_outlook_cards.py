"""PRD 902: Outlook host card JSON, offline and signed OpenUrl only."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from tilo_channels.card_model import card_to_neutral
from tilo_channels.links import CardState, KeyRing, LinkService
from tilo_channels.outlook_cards import render_outlook_card

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures" / "outlook_cards"


def source(name="gate_save_file_reversible"):
    path = ROOT / "contracts" / "fixtures" / "card" / "valid" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def issued(card):
    service = LinkService(
        keys=KeyRing({"test": bytes(range(32))}, "test"),
        nonces=Mock(),
        clock=lambda: datetime(2026, 10, 14, tzinfo=UTC),
        cards=lambda _: CardState(card, False),
        base_url="https://tilo.example",
    )
    return service.issue(card_id=card["id"], user_id="u_test", action="open")


@pytest.mark.parametrize("tier", ["T1", "T2", "T3"])
def test_FR_UX_17_outlook_golden(tier, monkeypatch):
    monkeypatch.setattr("socket.socket.connect", Mock(side_effect=AssertionError("network forbidden")))
    card = source()
    card["gate"]["risk_tier"] = tier
    before = copy.deepcopy(card)
    link = issued(card)
    result = render_outlook_card(card_to_neutral(card, link))
    expected = json.loads((FIXTURES / f"{tier}.json").read_text(encoding="utf-8"))
    expected["actions"][0]["url"] = link.url
    assert result == expected
    assert card == before


@pytest.mark.parametrize(
    "name", ["needs_you_compare_basis", "meeting_budget_split", "consent_drive_folder", "gate_send_reply"]
)
def test_FR_UX_17_outlook_all_kinds_open_only(name):
    card = source(name)
    link = issued(card)
    result = render_outlook_card(card_to_neutral(card, link))
    assert result["actions"] == [{"type": "Action.OpenUrl", "title": "Open card securely", "url": link.url}]
    assert "Action.Submit" not in json.dumps(result)
    assert "Input." not in json.dumps(result)


@pytest.mark.parametrize("case", ["long", "untrusted", "redacted"])
def test_FR_UX_17_outlook_edge_golden(case):
    card = source()
    card["what_happened"] = {
        "long": "x" * 2100,
        "untrusted": "@channel <at>everyone</at> **bold** [click](https://evil.example)",
        "redacted": "password=fixture-password",
    }[case]
    result = render_outlook_card(card_to_neutral(card, issued(card)))
    assert result["body"][0] == json.loads((FIXTURES / f"{case}.json").read_text(encoding="utf-8"))
    text = " ".join(block["text"] for block in result["body"])
    assert all(s not in text for s in ("@channel", "<at>", "[click](", "fixture-password"))
    assert all(len(block["text"]) <= 2000 for block in result["body"])
