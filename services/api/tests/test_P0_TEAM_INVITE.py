"""P0-TEAM-INVITE acceptance tests (OWNER-REVIEW-LIVE28 item 4).

Specification:
"inviting a member by email does not work. Reproduce (API create-invite -> outbox -> approval
-> send via Gmail connector fake), find why nothing arrives (approval never surfaces? send not wired?
wrong route?), fix. The person must see the pending invite in Needs you, and after approval it sends
(fake in tests). Plain errors in the UI."
"""

from __future__ import annotations

from _team_routes_lib import (
    APPROVER,
    OWNER,
    state,
    team_api,
)


def test_P0_TEAM_INVITE_reproduce_approval_surfaces_in_needs_you_and_sends_on_approval() -> None:
    """Reproduction and verification:
    1. POST /v1/team/invites creates the pending invite and stages the outbox/gate card.
    2. Before approval: nothing is sent via Gmail (len(api.sent) == 0).
    3. The gate card appears in "Needs you" (GET /cards) and GET /worlds/{desk_world}/cards.
    4. Answering with "approve" via POST /worlds/{desk_world}/cards/{card_id}/answer
       resolves the gate and dispatches the invitation via the Gmail connector fake.
    """
    with team_api(state(names={"tm_main": "Product studio"})) as api:
        # Step 1: Create invite
        res = api.post("/v1/team/invites", {"email": "alex@example.com", "role": "Member"})
        assert res.status_code == 201, res.text
        data = res.json()
        assert "invite_id" in data
        invite_id = data["invite_id"]

        # The invite must be recorded in team invites
        assert invite_id in api.store.read().invites
        assert api.store.read().invites[invite_id] == {"email": "alex@example.com", "role": "Member"}

        # Step 2: Before approval, NOTHING must be sent
        assert len(api.sent) == 0, "Email must not be sent before person approval"

        # Step 3: The person must see the pending invite in Needs you (GET /cards)
        cards_res = api.get("/cards")
        assert cards_res.status_code == 200, cards_res.text
        feed = cards_res.json()["cards"]
        invite_cards = [
            c
            for c in feed
            if c["card"].get("kind") == "gate" and "alex@example.com" in c["card"].get("gate", {}).get("recipients", [])
        ]
        assert len(invite_cards) == 1, f"Expected 1 gate card in Needs you, got {feed}"
        card_item = invite_cards[0]
        card = card_item["card"]
        world_id = card_item["world_id"]
        card_id = card_item["card_id"]

        assert card["gate"]["action"]["connector"] == "gmail"
        assert card["gate"]["action"]["type"] == "send_email"
        assert card["gate"]["risk_tier"] == "T2"
        assert "alex@example.com" in card["what_happened"]
        assert any(opt["id"] == "approve" for opt in card["options"])

        # Also visible on the desk world's cards endpoint
        desk_cards_res = api.get(f"/worlds/{world_id}/cards")
        assert desk_cards_res.status_code == 200
        assert any(c["id"] == card_id for c in desk_cards_res.json())

        # Step 4: After approval, it sends via the Gmail connector fake
        answer_res = api.post(
            f"/worlds/{world_id}/cards/{card_id}/answer",
            {"option": "approve", "channel": "web"},
        )
        assert answer_res.status_code == 200, answer_res.text
        assert answer_res.json() == {"outcome": "answered"}

        # Verified sent via fake Gmail adapter
        assert len(api.sent) == 1
        entry = api.sent[0]
        assert entry["action_type"] == "send_email"
        assert entry["connector"] == "gmail"
        assert entry["recipients"] == ["alex@example.com"]
        assert entry["risk_tier"] == "T2"
        assert entry["authz"] == {"by": "person", "ref": OWNER, "at": api.now}
        assert api.outbox.get(entry["id"])["state"] == "sent"

        # The card is now closed / resolved and removed from open Needs you feed
        after_cards = api.get("/cards").json()["cards"]
        assert not any(c["card_id"] == card_id for c in after_cards)


def test_P0_TEAM_INVITE_hold_leaves_invite_held_and_sends_nothing() -> None:
    """Holding the gate card keeps the invite pending and sends nothing."""
    with team_api(state(names={"tm_main": "Product studio"})) as api:
        res = api.post("/v1/team/invites", {"email": "sarah@example.com", "role": "Approver"})
        assert res.status_code == 201, res.text

        cards_res = api.get("/cards")
        feed = cards_res.json()["cards"]
        invite_card = next(c for c in feed if "sarah@example.com" in c["card"].get("gate", {}).get("recipients", []))

        # Hold the card
        ans = api.post(
            f"/worlds/{invite_card['world_id']}/cards/{invite_card['card_id']}/answer",
            {"option": "hold", "channel": "web"},
        )
        assert ans.status_code == 200

        # Nothing is sent
        assert len(api.sent) == 0


def test_P0_TEAM_INVITE_plain_errors_in_api() -> None:
    """Plain errors in the API with no raw codes or leaked internal details."""
    with team_api() as api:
        # Invalid role
        res = api.post("/v1/team/invites", {"email": "valid@example.com", "role": "Owner"})
        assert res.status_code == 422
        assert res.json()["detail"] == "Invite as Approver, Member or Viewer."

        # Valid invite
        res = api.post("/v1/team/invites", {"email": "dup@example.com", "role": "Member"})
        assert res.status_code == 201

        # Duplicate email
        dup = api.post("/v1/team/invites", {"email": "dup@example.com", "role": "Viewer"})
        assert dup.status_code == 409
        assert dup.json()["detail"] == "That address is already invited."

        # Non-owner cannot invite
        forbidden = api.as_(APPROVER).post("/v1/team/invites", {"email": "other@example.com", "role": "Member"})
        assert forbidden.status_code == 403
