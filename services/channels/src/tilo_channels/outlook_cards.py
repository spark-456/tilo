"""Parked Outlook actionable-message card renderer (PRD 902 / FR-UX-17).

Pure JSON projection, with no imports from app routes and no send capability.
Outlook delivery/envelopes and host registration are outside this preparation.
"""

from typing import Any

from tilo_channels.card_model import NeutralCard


def render_outlook_card(card: NeutralCard) -> dict[str, Any]:
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.0",
        "body": [{"type": "TextBlock", "text": line, "wrap": True} for line in card.lines],
        "actions": [{"type": "Action.OpenUrl", "title": "Open card securely", "url": card.open_url}],
    }
