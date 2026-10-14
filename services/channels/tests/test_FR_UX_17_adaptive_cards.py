"""PRD 902 / FR-UX-17: inert renderer, recorded contract inputs, no network."""

import copy
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from tilo_channels.adaptive_cards import render_adaptive_card
from tilo_channels.card_model import card_to_neutral
from tilo_channels.links import CardState, KeyRing, LinkService

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures" / "adaptive_cards"


def source(name="gate_save_file_reversible"):
    return json.loads((ROOT / "contracts" / "fixtures" / "card" / "valid" / f"{name}.json").read_text())


def issued(card):
    # Test-only key and in-memory ports; the renderer itself never issues a link.
    service = LinkService(
        keys=KeyRing({"test": bytes(range(32))}, "test"),
        nonces=Mock(),
        clock=lambda: datetime(2026, 10, 14, tzinfo=UTC),
        cards=lambda _: CardState(card, False),
        base_url="https://tilo.example",
    )
    return service.issue(card_id=card["id"], user_id="u_test", action="open")


@pytest.mark.parametrize("tier", ["T1", "T2", "T3"])
def test_FR_UX_17_adaptive_golden(tier, monkeypatch):
    monkeypatch.setattr("socket.socket.connect", Mock(side_effect=AssertionError("network forbidden")))
    card = source()
    card["gate"]["risk_tier"] = tier
    before = copy.deepcopy(card)
    link = issued(card)
    rendered = render_adaptive_card(card_to_neutral(card, link))
    expected = json.loads((FIXTURES / f"{tier}.json").read_text())
    expected["actions"][0]["url"] = link.url
    assert rendered == expected
    assert card == before
    assert rendered["actions"] == [{"type": "Action.OpenUrl", "title": "Open card securely", "url": link.url}]
    assert link.token not in repr(card_to_neutral(card, link))


@pytest.mark.parametrize(
    "name", ["needs_you_compare_basis", "meeting_budget_split", "consent_drive_folder", "gate_send_reply"]
)
def test_FR_UX_17_all_kinds_open_only(name):
    card = source(name)
    result = render_adaptive_card(card_to_neutral(card, issued(card)))
    assert [a["type"] for a in result["actions"]] == ["Action.OpenUrl"]
    assert "Action.Submit" not in json.dumps(result)
    assert "Input." not in json.dumps(result)


def test_FR_UX_17_untrusted_redacted_bounded_and_immutable():
    card = source()
    card["what_happened"] = "@channel @here <at>everyone</at> <!channel> [click](https://evil.example) **bold**"
    card["why_it_matters"] = "password=fixture-password " + "x" * 9000
    link = issued(card)
    model = card_to_neutral(card, link)
    text = " ".join(model.lines)
    assert all(s not in text for s in ("@channel", "@here", "<at>", "<!channel>", "fixture-password", "[click]("))
    assert all(len(line) <= 2000 for line in model.lines)
    assert "\u2026" in text
    assert model.open_url == link.url


@pytest.mark.parametrize(
    "change",
    [
        {"card_id": "different-card"},
        {"action": "answer"},
        {"option": "approve"},
        {"url": "javascript:alert(1)"},
        {"url": "http://tilo.example/l/token"},
        {"url": "https://user:pass@tilo.example/l/token"},
        {"url": "https://tilo.example/l/token#fragment"},
        {"url": "https://tilo.example/l/token?redirect=evil"},
        {"url": "https://tilo.example/other"},
    ],
)
def test_FR_UX_17_reject_unbound_or_unsafe_links(change):
    card = source()
    with pytest.raises(ValueError, match="card-bound HTTPS"):
        card_to_neutral(card, replace(issued(card), **change))


@pytest.mark.parametrize("case", ["long", "untrusted", "redacted"])
def test_FR_UX_17_edge_golden(case):
    card = source()
    card["what_happened"] = {
        "long": "x" * 2100,
        "untrusted": "@channel <at>everyone</at> **bold** [click](https://evil.example)",
        "redacted": "password=fixture-password",
    }[case]
    rendered = render_adaptive_card(card_to_neutral(card, issued(card)))
    assert rendered["body"][0] == json.loads((FIXTURES / f"{case}.json").read_text())
