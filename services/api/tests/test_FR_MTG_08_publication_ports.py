"""FR-MTG-08 fresh publication guards, offline delegation and SDK-delay regressions."""

from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from tilo_api.followup_autopilot_state import FirestoreCards, FirestoreStops
from tilo_api.followup_publication_ports import PublicationCards, PublicationOutbox, PublicationStops

CASES = [
    (PublicationCards, "get", ("u_owner", "card")),
    (PublicationCards, "create", ("u_owner", "card", {"body": "draft"})),
    (PublicationCards, "put", ("u_owner", "card", {"body": "draft"})),
    (PublicationStops, "add", ("u_owner", "card")),
    (PublicationStops, "pending", ()),
    (PublicationStops, "remove", ("u_owner", "card")),
    (PublicationOutbox, "enqueue", ({"id": "entry"}, {"approved": False})),
    (PublicationOutbox, "cancel", ("entry",)),
    (PublicationOutbox, "get", ("entry",)),
    (PublicationOutbox, "get_by_idempotency_key", ("w_meet", "stable-key")),
    (PublicationOutbox, "revoke", ("w_meet", "stable-key")),
]


@pytest.mark.parametrize("port_type,method,args", CASES)
def test_FR_MTG_08_publication_check_immediately_precedes_each_delegation(port_type, method, args):
    events, result = [], object()
    inner = Mock()

    def delegate(*received):
        events.append("delegate")
        assert len(received) == len(args)
        assert all(actual is expected for actual, expected in zip(received, args, strict=True))
        return result

    getattr(inner, method).side_effect = delegate
    port = port_type(inner, lambda: events.append("check"))
    assert events == []
    assert getattr(port, method)(*args) is result
    assert events == ["check", "delegate"]
    # The second operation must revalidate instead of caching the first check.
    assert getattr(port, method)(*args) is result
    assert events == ["check", "delegate", "check", "delegate"]
    assert getattr(inner, method).call_count == 2


@pytest.mark.parametrize("port_type,method,args", CASES)
def test_FR_MTG_08_publication_refusal_never_delegates(port_type, method, args):
    inner, calls = Mock(), []
    refusal = HTTPException(409, "source_changed")

    def refuse():
        calls.append("check")
        raise refusal

    port = port_type(inner, refuse)
    with pytest.raises(HTTPException) as caught:
        getattr(port, method)(*args)
    assert caught.value is refusal
    assert calls == ["check"]
    assert inner.mock_calls == []


def test_FR_MTG_08_publication_outbox_has_no_dispatch_capability():
    inner = Mock()
    inner.dispatch_due = Mock()
    assert not hasattr(PublicationOutbox(inner, lambda: None), "dispatch_due")


@pytest.mark.parametrize(
    "store_type,method,args",
    [
        (FirestoreCards, "create", ("u_owner", "card", {"body": "draft"})),
        (FirestoreCards, "put", ("u_owner", "card", {"body": "draft"})),
        (FirestoreStops, "add", ("u_owner", "card")),
        (FirestoreStops, "remove", ("u_owner", "card")),
    ],
)
def test_FR_MTG_08_sdk_document_delay_rechecks_before_mutation(store_type, method, args):
    events, fresh = [], [True]
    client, document = Mock(), Mock()
    refusal = HTTPException(409, "source_changed")

    def lookup(path):
        events.append("document")
        fresh[0] = False  # Source expires or is deleted while resolving the document.
        return document

    def check():
        events.append("check")
        if not fresh[0]:
            raise refusal

    client.document.side_effect = lookup
    store = store_type(
        client,
        org_id="org_tilo",
        owner="u_owner",
        world_id="w_meet",
        run_id="r_meet",
        before_publication=check,
    )
    with pytest.raises(HTTPException) as caught:
        getattr(store, method)(*args)
    assert caught.value is refusal
    assert events[-2:] == ["document", "check"]
    assert document.mock_calls == []
