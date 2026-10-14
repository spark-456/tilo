"""PRD 902 / FR-UX-17: offline Slack cards with signed-link-only actions."""

import copy
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from tilo_channels.card_model import NeutralCard, card_to_neutral
from tilo_channels.links import CardState, KeyRing, LinkService

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures" / "slack_cards"


def source(name="gate_save_file_reversible"):
    return json.loads((ROOT / "contracts" / "fixtures" / "card" / "valid" / f"{name}.json").read_text(encoding="utf-8"))


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
def test_FR_UX_17_slack_golden(tier, monkeypatch):
    monkeypatch.setattr("socket.socket.connect", Mock(side_effect=AssertionError("network forbidden")))
    from tilo_channels.slack_cards import render_slack_card

    card = source()
    card["gate"]["risk_tier"] = tier
    before = copy.deepcopy(card)
    link = issued(card)
    model = card_to_neutral(card, link)
    expected = json.loads((FIXTURES / f"{tier}.json").read_text(encoding="utf-8"))
    expected["blocks"][-1]["elements"][0]["url"] = link.url
    assert render_slack_card(model) == expected
    assert card == before
    assert link.token not in repr(model)


@pytest.mark.parametrize("case", ["long", "untrusted", "redacted"])
def test_FR_UX_17_slack_edge_golden(case):
    from tilo_channels.slack_cards import render_slack_card

    card = source()
    card["what_happened"] = {
        "long": "x" * 2100,
        "untrusted": "@channel @here <!channel> <@U123> *bold* https://evil.example",
        "redacted": "password=fixture-password",
    }[case]
    rendered = render_slack_card(card_to_neutral(card, issued(card)))
    expected = json.loads((FIXTURES / f"{case}.json").read_text(encoding="utf-8"))
    expected["blocks"][-1]["elements"][0]["url"] = rendered["blocks"][-1]["elements"][0]["url"]
    assert rendered == expected
    text = rendered["text"] + " ".join(b["text"]["text"] for b in rendered["blocks"][:-1])
    assert all(s not in text for s in ("@channel", "@here", "<!channel>", "<@U123>", "fixture-password"))
    assert len(rendered["text"]) <= 2000
    assert all(b["text"]["type"] == "plain_text" for b in rendered["blocks"][:-1])


@pytest.mark.parametrize(
    "name", ["needs_you_compare_basis", "meeting_budget_split", "consent_drive_folder", "gate_send_reply"]
)
def test_FR_UX_17_slack_all_kinds_use_existing_open_link(name):
    from tilo_channels.slack_cards import render_slack_card

    card = source(name)
    link = issued(card)
    result = render_slack_card(card_to_neutral(card, link))
    assert result["blocks"][-1]["elements"] == [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Open card securely", "emoji": False},
            "url": link.url,
        }
    ]
    assert "action_id" not in json.dumps(result)
    assert result["mrkdwn"] is False and result["parse"] == "none"
    assert result["unfurl_links"] is False and result["unfurl_media"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"card_id": "different"},
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
def test_FR_UX_17_slack_reject_unbound_links(change):
    card = source()
    with pytest.raises(ValueError, match="card-bound HTTPS"):
        card_to_neutral(card, replace(issued(card), **change))


@pytest.mark.parametrize("lines,url", [((), "url"), (("x",) * 50, "url"), (("x" * 3001,), "url"), (("x",), "x" * 3001)])
def test_FR_UX_17_slack_refuse_oversized_projection(lines, url):
    from tilo_channels.slack_cards import render_slack_card

    with pytest.raises(ValueError, match="Slack"):
        render_slack_card(NeutralCard(lines, url))
