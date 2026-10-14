"""Inert Slack Block Kit projection (PRD 902 / FR-UX-17).

Use card_to_neutral with an existing owner-authorized IssuedLink first. There is
no signing, interaction handler, delivery client or application wiring here.
Future delivery must retain the existing outbox/policy T3 approval boundary.
"""

from typing import Any

from tilo_channels.card_model import NeutralCard


def render_slack_card(card: NeutralCard) -> dict[str, Any]:
    """Render display-only text and one URL button into Slack's message shape."""
    if not card.lines or len(card.lines) > 49 or any(not line or len(line) > 3000 for line in card.lines):
        raise ValueError("card exceeds Slack section limits")
    if len(card.open_url) > 3000:
        raise ValueError("signed link exceeds Slack button URL limit")
    return {
        "text": " ".join(card.lines)[:2000],
        "mrkdwn": False,
        "parse": "none",
        "unfurl_links": False,
        "unfurl_media": False,
        "blocks": [
            {"type": "section", "text": {"type": "plain_text", "text": line, "emoji": False}} for line in card.lines
        ]
        + [
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open card securely", "emoji": False},
                        "url": card.open_url,
                    }
                ],
            }
        ],
    }
