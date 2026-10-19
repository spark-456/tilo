"""FR-PA-06b (stacked on FR-PA-06; FR-CHN-07, PE-10, PE-30, SEC-08, SEC-15): the HTTP side of the plate digest's
signed single-use Done and Snooze links.

`GET /l/<token>` only renders a confirm page and consumes nothing (a mail scanner or prefetch must not redeem);
`POST /l/<token>` redeems once and writes the existing `work_item.changed` (done, snoozed) through the people write
path, so the owner check is `tilo_people.access.decide`. Missing signing key, nonce store or stores fail closed.
Fake secrets are assembled at run time; no mail is sent and no model or network is touched.
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from _ppl11a_lib import NOW, ORG, PRIYA, SAM, own_item
from _ppl11c_lib import emitted, work_rig
from fastapi import Request
from tilo_api import access, appcheck, deps, durable_store, plate_links
from tilo_api.people_plate import build_plate
from tilo_channels.digest import DigestArtifacts  # noqa: F401  (the digest package must import in the API image)
from tilo_channels.links import CardState, KeyRing, LinkService
from tilo_channels.plate_digest import PlateDigestBuilder

BASE = "https://api.tilo.example"


def _builder(nonces: Any = None, clock: Any = None) -> PlateDigestBuilder:
    ring = KeyRing({"k_test": secrets.token_bytes(32)}, active="k_test")
    return PlateDigestBuilder(base_url=BASE, keys=ring, nonces=nonces or plate_links.MemoryNonces(), clock=clock)


def _rig(people_rig: Any, builder: PlateDigestBuilder | None = None) -> tuple[Any, PlateDigestBuilder]:
    rig = work_rig(people_rig)
    made = builder or _builder()
    rig.app.dependency_overrides[plate_links.get_link_builder] = lambda: made
    return rig, made


def _links(rig: Any, builder: PlateDigestBuilder, user: str = PRIYA, item_id: str = "wi_own1") -> tuple[str, str]:
    """(done path, snooze path) of one item, minted from the person's real plate rows."""
    plate = build_plate(rig.real, rig.sources, rig.owners, ORG, user, NOW)
    assert plate is not None
    digest = builder.build(user_id=user, plate=plate, now=dt.datetime(2026, 10, 6, 10, 0, tzinfo=dt.UTC))
    assert digest is not None
    item = next(i for i in digest.items if i.item_id == item_id)
    return (item.done_url.removeprefix(BASE), item.snooze_url.removeprefix(BASE))


def test_FR_PA_06b_a_get_renders_a_confirm_page_and_redeems_nothing(people_rig: Any) -> None:
    rig, builder = _rig(people_rig)
    done, _snooze = _links(rig, builder)

    for _ in range(3):  # a scanner, a prefetch and a person's own preview
        got = rig.client.get(done)
        assert got.status_code == 200 and "<form" in got.text and 'method="post"' in got.text
        assert done.rsplit("/", 1)[1] not in got.text  # the page never echoes the token
        assert got.headers["cache-control"] == "no-store" and got.headers["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in got.headers["content-security-policy"]
    assert rig.stored("work_items", "wi_own1")["status"] == "open" and emitted(rig) == []

    posted = rig.client.post(done)
    assert posted.status_code == 200
    assert rig.stored("work_items", "wi_own1")["status"] == "done"


def test_FR_PA_06b_post_done_writes_one_work_item_changed_in_the_desk_world_and_is_single_use(people_rig: Any) -> None:
    rig, builder = _rig(people_rig)
    done, snooze = _links(rig, builder)

    assert rig.client.post(done).status_code == 200
    assert [(w, p["type"], p["data"]["change"]) for w, p in emitted(rig)] == [
        ("w_desk_priya", "work_item.changed", "done")
    ]
    assert emitted(rig)[0][1]["data"]["work_item_id"] == "wi_own1"

    again = rig.client.post(done)
    assert again.status_code in (404, 410) and len(emitted(rig)) == 1  # reuse refused, nothing more written
    assert rig.client.post(snooze).status_code == 200  # the other link of the item is its own nonce...
    assert len(emitted(rig)) == 1  # ...but the item is done now, so the write is refused and says so


def test_FR_PA_06b_post_snooze_moves_the_item_to_tomorrow_morning_in_the_persons_zone(people_rig: Any) -> None:
    rig, builder = _rig(people_rig)
    _done, snooze = _links(rig, builder)

    assert rig.client.post(snooze).status_code == 200
    item = rig.stored("work_items", "wi_own1")
    assert item["status"] == "open" and item["history"][-1]["change"] == "snoozed"
    zone = ZoneInfo(rig.stored("persons", PRIYA)["time_zone"])
    until = dt.datetime.fromisoformat(item["snoozed_until"].replace("Z", "+00:00")).astimezone(zone)
    now_local = dt.datetime(2026, 10, 6, 10, 0, tzinfo=dt.UTC).astimezone(zone)
    assert (until.date() - now_local.date()).days == 1 and (until.hour, until.minute) == (9, 0)
    assert [p["data"]["change"] for _w, p in emitted(rig)] == ["snoozed"]


def test_FR_PA_06b_a_link_for_another_persons_item_changes_nothing(people_rig: Any) -> None:
    rig, builder = _rig(people_rig)
    rig.add("work_items", own_item("wi_sams", SAM))
    plate = build_plate(rig.real, rig.sources, rig.owners, ORG, SAM, NOW)
    assert plate is not None
    digest = builder.build(user_id=SAM, plate=plate, now=dt.datetime(2026, 10, 6, 10, 0, tzinfo=dt.UTC))
    assert digest is not None
    # a link signed for PRIYA that names SAM's item (a forged-by-the-issuer case): the owner check is `decide`
    forged = builder._links(dt.datetime(2026, 10, 6, 10, 0, tzinfo=dt.UTC)).issue(  # noqa: SLF001
        card_id="wi_sams", user_id=PRIYA, action="answer", option="done"
    )

    got = rig.client.post(forged.url.removeprefix(BASE))
    assert got.status_code == 200 and "can't be changed" in got.text
    assert rig.stored("work_items", "wi_sams")["status"] == "open" and emitted(rig) == []


def test_FR_PA_06b_expired_tampered_and_unknown_links_get_one_generic_refusal(people_rig: Any) -> None:
    rig, builder = _rig(people_rig)
    done, _snooze = _links(rig, builder)
    token = done.rsplit("/", 1)[1]

    rig.set_now("2026-10-07T10:00:01.000Z")  # 24 h and 1 s after the link was made
    answers = {
        rig.client.post(done).status_code,
        rig.client.post("/l/" + token[:-3] + "AAA").status_code,
        rig.client.post("/l/not-a-token").status_code,
        rig.client.get("/l/not-a-token").status_code,
    }
    assert answers <= {404, 410}
    assert rig.stored("work_items", "wi_own1")["status"] == "open" and emitted(rig) == []


def test_FR_PA_06b_without_a_signing_key_the_route_fails_closed(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = work_rig(people_rig)
    for name in (plate_links.ENV_KEY, plate_links.ENV_KEY_ID, plate_links.ENV_BASE):
        monkeypatch.delenv(name, raising=False)

    assert rig.client.get("/l/anything").status_code == 503
    assert rig.client.post("/l/anything").status_code == 503
    monkeypatch.setenv(plate_links.ENV_KEY, "too short")
    monkeypatch.setenv(plate_links.ENV_BASE, BASE)
    assert rig.client.post("/l/anything").status_code == 503  # a short key is not a key
    assert emitted(rig) == []


def test_FR_PA_06b_a_missing_people_store_fails_closed_before_the_link_is_spent(people_rig: Any) -> None:
    rig, builder = _rig(people_rig)
    done, _snooze = _links(rig, builder)
    rig.unwire("people_stores")  # production default: 503 not_configured

    assert rig.client.post(done).status_code == 503
    rig.app.dependency_overrides.pop(plate_links.get_link_builder)
    rig.app.dependency_overrides[plate_links.get_link_builder] = lambda: builder
    rig._wire()  # noqa: SLF001  (the store is back)
    assert rig.client.post(done).status_code == 200  # the earlier refusal did not burn the link


def test_FR_PA_06b_the_link_routes_are_public_to_the_gate_and_nothing_else_is(people_rig: Any) -> None:
    rig, builder = _rig(people_rig)
    done, _snooze = _links(rig, builder)
    assert ("GET", "/l/x") not in access.PUBLIC_ROUTES  # the exact-route pin of SEC-15 is untouched
    assert access.public_link("GET", done) and access.public_link("POST", done)
    assert (
        not access.public_link("PUT", done)
        and not access.public_link("GET", "/l/")
        and not access.public_link("GET", "/v1/plate")
    )
    assert not access.public_link("GET", "/l/a/b") and not access.public_link("GET", "/l/a?x=1")


def test_FR_PA_06b_the_token_never_reaches_the_access_log() -> None:
    token = "k_test." + "A" * 40 + "." + "B" * 43
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, "%s - %s %s", ("1.2.3.4", "POST", f"/l/{token}"), None
    )
    assert plate_links.MaskToken().filter(record)
    assert token not in record.getMessage() and "/l/<redacted>" in record.getMessage()


def test_FR_PA_06b_nonces_are_kept_as_a_hash_and_consumed_once() -> None:
    created: dict[str, dict[str, Any]] = {}

    class _Exists(Exception):
        pass

    class _Doc:
        def __init__(self, path: str) -> None:
            self.path = path

        def create(self, data: dict[str, Any]) -> None:
            if self.path in created:
                raise plate_links.ALREADY_EXISTS("exists")
            created[self.path] = data

    class _Client:
        def document(self, path: str) -> _Doc:
            return _Doc(path)

    store = plate_links.FirestoreNonces(_Client(), org_id=ORG)
    expires = dt.datetime(2026, 10, 7, tzinfo=dt.UTC)
    assert store.consume("nonce-value-1", expires) is True
    assert store.consume("nonce-value-1", expires) is False
    assert store.consume("nonce-value-2", expires) is True
    assert all("nonce-value" not in path and set(data) == {"expires_at"} for path, data in created.items())


def test_FR_PA_06b_the_daily_trigger_is_off_by_default_and_never_sends_without_a_mailer(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = work_rig(people_rig)
    sent: list[tuple[str, dict[str, Any]]] = []

    class _Mailer:
        def deliver(self, user_id: str, plate: Any, *, now: str) -> bool:
            sent.append((user_id, plate))
            return True

    request = Request({"type": "http", "app": rig.app, "headers": [], "method": "POST", "path": "/"})
    overrides = rig.app.dependency_overrides
    overrides[plate_links.get_plate_mailer] = lambda: _Mailer()
    monkeypatch.delenv(plate_links.ENV_DIGEST, raising=False)
    assert plate_links.sweep(request, "2026-10-06T05:00:00.000Z") == 0 and sent == []  # off by default

    monkeypatch.setenv(plate_links.ENV_DIGEST, "1")
    assert plate_links.sweep(request, "2026-10-06T02:00:00.000Z") == 0  # 07:30 IST: before the window
    assert sent == []
    count = plate_links.sweep(request, "2026-10-06T05:00:00.000Z")  # 10:30 IST, inside 09:00 to 18:00
    assert count == len(sent) >= 1
    assert all(plate["user"] == user for user, plate in sent)

    overrides.pop(plate_links.get_plate_mailer)  # production default: no mailer is wired, so nothing is sent
    sent.clear()
    assert plate_links.sweep(request, "2026-10-06T05:00:00.000Z") == 0 and sent == []


def test_FR_PA_06b_a_base_url_that_is_not_plain_https_is_not_configured(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = work_rig(people_rig)
    monkeypatch.setenv(plate_links.ENV_KEY, secrets.token_hex(32))
    for bad in ("http://api.tilo.example", "https://u:p@api.tilo.example", "https://api.tilo.example/?a=1"):
        monkeypatch.setenv(plate_links.ENV_BASE, bad)
        assert rig.client.get("/l/anything").status_code == 503
    assert emitted(rig) == []


def test_FR_PA_06b_the_event_says_it_came_from_an_email_link_and_the_request_cannot_choose_the_viewer(
    people_rig: Any,
) -> None:
    rig, builder = _rig(people_rig)
    done, _snooze = _links(rig, builder)

    posted = rig.client.post(done + "?viewer=u_owner&now=2030-01-01T00:00:00.000Z", headers={"x-viewer": "u_owner"})
    assert posted.status_code == 200
    ((_world, part),) = emitted(rig)
    assert part["summary"] == "A work item was marked done (email link)." and part["actor"] == PRIYA
    assert rig.stored("work_items", "wi_own1")["history"][-1]["by"] == PRIYA  # the redeemed person, nobody else


def test_FR_PA_06b_a_done_link_of_an_earlier_mail_never_re_marks_a_done_item(people_rig: Any) -> None:
    rig, builder = _rig(people_rig)
    first, _ = _links(rig, builder)
    second, _ = _links(rig, builder)  # another mail, another nonce, the same item

    assert rig.client.post(first).status_code == 200
    again = rig.client.post(second)
    assert again.status_code == 200 and "can't be changed" in again.text
    assert len(emitted(rig)) == 1 and len(rig.stored("work_items", "wi_own1")["history"]) == 2


def test_FR_PA_06b_a_lost_compare_and_set_applies_nothing_and_says_open_tilo(people_rig: Any) -> None:
    rig, builder = _rig(people_rig)
    done, _snooze = _links(rig, builder)
    rig.conflicting_stores("work_items")  # another writer got there first

    got = rig.client.post(done)
    assert got.status_code == 200 and "can't be changed" in got.text
    assert rig.stored("work_items", "wi_own1")["status"] == "open" and emitted(rig) == []


def test_FR_PA_06b_a_store_that_raises_after_the_link_is_spent_is_never_a_500_or_a_retry(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, builder = _rig(people_rig)
    done, _snooze = _links(rig, builder)

    def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("store down")

    monkeypatch.setattr(rig.stores.work_items, "get", broken)
    got = rig.client.post(done)
    assert got.status_code == 200 and "Open Tilo" in got.text or "open Tilo" in got.text
    assert "Retry-After" not in got.headers and emitted(rig) == []
    monkeypatch.undo()
    again = rig.client.post(done)  # spent: nothing retries it
    assert again.status_code == 410 and rig.stored("work_items", "wi_own1")["status"] == "open"


def test_FR_PA_06b_a_desk_event_that_cannot_be_recorded_leaves_the_row_where_it_was(people_rig: Any) -> None:
    rig, builder = _rig(people_rig)
    done, _snooze = _links(rig, builder)
    rig.desks.fail = True  # the event cannot be recorded, so the write is undone (PE-30)

    got = rig.client.post(done)
    assert got.status_code == 200 and "can't be changed" in got.text
    assert rig.stored("work_items", "wi_own1")["status"] == "open"


# -- the deployed route: a mail click has no sign-in (security review 6b) ------------------------------------------


def _bare_deployed(people_rig: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, PlateDigestBuilder, list[str]]:
    """The deployed-style rig with NO principal override and NO store, writer or Desk override: what is left is the
    process's own durable seams (`deps._people_stores`, `durable_store.deployed`), as a Cloud Run revision has them. The
    list records every time the durable store was opened."""
    rig = people_rig(deployed=True)
    rig.add_people()
    rig.add("work_items", own_item("wi_own1", PRIYA))
    rig.as_user(PRIYA)
    made = _builder()
    rig.app.dependency_overrides[plate_links.get_link_builder] = lambda: made
    links = [deps.get_current_principal, deps.get_people_stores, deps.get_event_writer, deps.get_desk_worlds]
    for seam in links:
        rig.app.dependency_overrides.pop(seam, None)
    opened: list[str] = []
    store = rig.event_store
    monkeypatch.setattr(store, "load_path", lambda params: store, raising=False)

    def deployed() -> Any:
        opened.append("deployed")
        return store, rig.events

    monkeypatch.setattr(deps, "_people_stores", rig.stores)
    monkeypatch.setattr(durable_store, "deployed", deployed)
    return rig, made, opened


def test_FR_PA_06b_a_deployed_mail_click_with_no_sign_in_applies_once(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, builder, _opened = _bare_deployed(people_rig, monkeypatch)
    done, _snooze = _links(rig, builder)

    assert rig.client.get(done).status_code == 200
    posted = rig.client.post(done)
    assert posted.status_code == 200 and "Marked done" in posted.text
    assert rig.stored("work_items", "wi_own1")["status"] == "done"
    assert [p["type"] for _w, p in emitted(rig)] == ["work_item.changed"]
    desk = emitted(rig)[0][0]
    assert desk.startswith("w_desk_") and rig.event_store.worlds[desk].owner == PRIYA  # the token's person, nobody else
    assert rig.client.post(done).status_code == 410 and len(emitted(rig)) == 1  # single use


def test_FR_PA_06b_with_app_check_enforced_a_link_request_is_not_401_and_a_normal_route_still_is(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Refuses:
        def verify(self, token: str) -> Any:
            raise appcheck.TokenRefused("missing")

    rig, builder, _opened = _bare_deployed(people_rig, monkeypatch)
    monkeypatch.setenv(appcheck.ENFORCE_ENV, "1")
    rig.app.dependency_overrides[deps.get_app_check_verifier] = lambda: Refuses()
    done, _snooze = _links(rig, builder)

    assert rig.client.get("/v1/plate").status_code == 401  # the exemption is the link prefix only
    assert rig.client.get("/v1/plate").json()["code"] == "app_check_required"
    assert rig.client.get("/l/x/y").status_code == 401  # not one path segment: not a link
    assert rig.client.get(done).status_code == 200
    assert rig.client.post(done).status_code == 200
    assert rig.stored("work_items", "wi_own1")["status"] == "done" and len(emitted(rig)) == 1


def test_FR_PA_06b_an_unsigned_or_malformed_token_never_reaches_a_store_or_the_event_writer(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, builder, opened = _bare_deployed(people_rig, monkeypatch)
    other_key, _snooze = _links(rig, _builder())  # same key id, another key: a forged MAC
    tokens = ["x", "a.b.c", "k_test.AAAA.BBBB", "A" * 512, other_key.rsplit("/", 1)[1]]

    for token in tokens:
        assert rig.client.get(f"/l/{token}").status_code == 404, token
        assert rig.client.post(f"/l/{token}").status_code == 410, token
    assert rig.client.post("/l/" + "A" * 513).status_code == 401  # over the path cap: not public, the gate answers
    assert opened == [] and rig.store_calls == [] and emitted(rig) == []
    assert rig.stored("work_items", "wi_own1")["status"] == "open"


def test_FR_PA_06b_a_question_card_link_cannot_be_spent_on_the_plate_route(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, builder, opened = _bare_deployed(people_rig, monkeypatch)
    card = {"kind": "needs_you", "rung": "needs_you", "gate": None, "consent": None, "answer_channels": ["email"]}
    nonces = plate_links.MemoryNonces()
    ring = builder._keys  # noqa: SLF001  (the same signing key as the plate links)
    other = LinkService(
        keys=ring,
        nonces=nonces,
        clock=lambda: dt.datetime(2026, 10, 6, 10, 0, tzinfo=dt.UTC),
        cards=lambda _id: CardState(card=card | {"options": [{"id": "done"}, {"id": "snooze"}]}, answered=False),
        base_url=BASE,
    )
    link = other.issue(card_id="c_question1", user_id=PRIYA, action="answer", option="done").url.removeprefix(BASE)

    assert rig.client.get(link).status_code == 404 and rig.client.post(link).status_code == 410
    assert opened == [] and emitted(rig) == []
