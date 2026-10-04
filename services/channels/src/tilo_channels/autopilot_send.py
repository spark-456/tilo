"""tilo_channels.autopilot_send: the text an Autopilot send carries (FR-CHN-13; PRD 11.4 Preview; OB-05; BQ-182).

The Gmail adapter reads an outbox entry's `item` through an ArtifactSource. `DraftArtifacts` is that source for
Autopilot cards: the card's subject and the cleaned body the person saw, at exactly the card's artifact version, plus
the In-Reply-To and References of the message the card answers (BQ-185).
The `Autopilot` records which card holds an artifact before any entry of that card is enqueued. Anything unknown, or
an index that does not match the card it points to, is a KeyError, which the adapter turns into a refused send.
tilo-channels never imports tilo_connectors (BQ-158); the service wiring hands this object to the adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tilo_channels.autopilot_state import CardStore
from tilo_channels.autopilot_t3 import clean_text

__all__ = ["ARTIFACT_INDEX", "DraftArtifacts", "index_artifact"]

ARTIFACT_INDEX = "#artifacts"  # card store namespace for artifact -> card; user ids are ^u_[0-9A-Za-z_]+$ (contracts)


def index_artifact(cards: CardStore, user_id: str, doc: Mapping[str, Any]) -> None:
    """Records the card that holds `doc`'s artifact (create-if-absent). ValueError when the artifact is already
    another card's: one artifact never serves two cards' text."""
    item = doc.get("item")
    if not isinstance(item, Mapping):
        return
    key, record = str(item["artifact_id"]), {"user_id": user_id, "card_id": doc["card_id"]}
    found = cards.get(ARTIFACT_INDEX, key)
    if found is None and cards.create(ARTIFACT_INDEX, key, record):
        return
    if (found or cards.get(ARTIFACT_INDEX, key)) != record:
        raise ValueError("this artifact belongs to another Autopilot card")


class DraftArtifacts:
    def __init__(self, *, cards: CardStore) -> None:
        self._cards = cards

    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]:
        where = self._cards.get(ARTIFACT_INDEX, artifact_id)
        doc = self._cards.get(str(where["user_id"]), str(where["card_id"])) if where else None
        if doc is None or doc.get("item") != {"artifact_id": artifact_id, "version": version}:
            raise KeyError("no Autopilot card holds this artifact version")
        text = {"subject": clean_text(doc["subject"]), "body_text": clean_text(doc["body"])}
        # BQ-185: the reply headers of the message the card answers; the adapter sends exactly these, or refuses
        return {
            "kind": "email",
            **text,
            "in_reply_to": doc.get("in_reply_to", ""),
            "references": doc.get("references", ""),
        }
