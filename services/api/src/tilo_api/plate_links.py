"""The HTTP side of the plate digest's emailed Done and Snooze links (FR-PA-06b; FR-CHN-07, SEC-08, PE-10, PE-30).

`GET /l/<token>` verifies the signature and expiry and shows a confirm page; it consumes nothing, so a mail scanner or a
prefetch never spends a link. `POST /l/<token>` redeems the single-use link (the nonce is consumed last) and applies it
through the existing work-item write path (`people_items.done_item` / `snooze_item`): the owner check is
`tilo_people.access.decide` on the redeemed person, one compare-and-set, one `work_item.changed` in the person's Desk
world, and the row moves only after that event is recorded (PE-30). A link is a bearer, so it is never logged (the
access log masks it), never put in a page, and only the nonce's SHA-256 is kept. Every refusal is one generic page.
Missing signing key, nonce store, people store or event writer fail closed (503) before anything is spent. A mail reply
is never read (PRD 10.3). `sweep` is the daily trigger hook the Scheduler's tick calls: off unless
`TILO_PLATE_DIGEST=1`, and it sends only through `plate_mailer` (the owner's standing L3 rule, the outbox, Gmail).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import logging
import os
import re
import threading
from pathlib import Path
from typing import Annotated, Any, Protocol
from zoneinfo import ZoneInfo

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from google.api_core.exceptions import AlreadyExists as ALREADY_EXISTS
from tilo_channels.links import KeyRing, LinkRefused
from tilo_channels.plate_digest import PlateActionPort, PlateDigestBuilder
from tilo_people.stores import PeopleStores

from tilo_api import access, deps, people_items, store_door
from tilo_api.people_events import WorkEvents, get_work_events
from tilo_api.people_plate import build_plate
from tilo_api.people_writes import Refusal, Writer

logger = logging.getLogger("tilo_api.plate_links")
ENV_KEY, ENV_KEY_ID, ENV_BASE = "TILO_LINK_SIGNING_KEY", "TILO_LINK_KEY_ID", "TILO_LINK_BASE_URL"
ENV_DIGEST = "TILO_PLATE_DIGEST"
_MIN_KEY = 32
MAX_PEOPLE = 500  # persons one tick looks at
_MEMORY_MAX = 10_000
PERSONAL = Path(__file__).resolve().parents[4] / "config" / "personal.yaml"
_HM = re.compile(r"([01]\d|2[0-3]):[0-5]\d\Z")
_TOKEN_IN_PATH = re.compile(r"^(/l/)[^/?\s]+")
_PAGES = {
    "done": ("Mark this item done?", "Done"),
    "snooze": ("Snooze this item until tomorrow morning?", "Snooze"),
}
_REFUSED = "This link is not valid, or it has already been used or has expired. Open Tilo to change your plate."
_CANT = "This item can't be changed from here any more. Open Tilo to see your plate."
_UNAVAILABLE = "Tilo could not apply this link. Open Tilo to change your plate."
_DONE = {"done": "Marked done.", "snooze": "Snoozed until tomorrow morning."}


class MaskToken(logging.Filter):
    """uvicorn's access log records the request path, which holds the bearer token: log `/l/<redacted>`."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > 2 and isinstance(args[2], str):
            record.args = (*args[:2], _TOKEN_IN_PATH.sub(r"\1<redacted>", args[2]), *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(MaskToken())


# -- single use: the nonce, kept as a hash ---------------------------------------------------------------------------


class MemoryNonces:
    """The nonce store of dev and tests (one process). Deployed, only `FirestoreNonces` is used."""

    def __init__(self) -> None:
        self._seen: dict[str, dt.datetime] = {}
        self._lock = threading.Lock()

    def consume(self, nonce: str, expires_at: dt.datetime) -> bool:
        key = hashlib.sha256(nonce.encode()).hexdigest()
        with self._lock:
            if key in self._seen:
                return False
            if len(self._seen) >= _MEMORY_MAX:  # dev and tests only: drop the one that expires first
                del self._seen[min(self._seen, key=self._seen.__getitem__)]
            self._seen[key] = expires_at
            return True


class FirestoreNonces:
    """`orgs/{org}/link_nonces/{sha256(nonce)}` with only `expires_at` (a Firestore TTL field). One `create`, so two
    redeemers of one link race to one winner whatever the database's lock mode."""

    def __init__(self, client: Any, *, org_id: str = deps.ORG_ID) -> None:
        self._client, self._org = client, org_id

    def consume(self, nonce: str, expires_at: dt.datetime) -> bool:
        path = f"orgs/{self._org}/link_nonces/{hashlib.sha256(nonce.encode()).hexdigest()}"
        try:
            self._client.document(path).create({"expires_at": expires_at})
        except ALREADY_EXISTS:
            return False
        return True


# -- the builder (signing key, base URL, nonce store) ----------------------------------------------------------------

_built: dict[tuple[str, str, str], PlateDigestBuilder] = {}
_lock = threading.Lock()


def _unconfigured() -> HTTPException:
    return HTTPException(status_code=503, detail="not_configured")


def _nonce_store() -> Any:
    if not access.enforced():
        return MemoryNonces()
    try:
        return FirestoreNonces(store_door.open_api_store(firestore_client_factory=store_door.client_factory).client)
    except (store_door.ApiStoreNotConfigured, store_door.ApiStoreUnavailable):
        raise _unconfigured() from None  # deployed memory would let a link be used once per instance


def get_link_builder() -> PlateDigestBuilder:
    """One builder per process for the configured key. 503 `not_configured` with no key, a key under 32 bytes, a base
    URL that is not https without user info, query or fragment, or, deployed, no durable nonce store."""
    key, kid, base = os.environ.get(ENV_KEY, ""), os.environ.get(ENV_KEY_ID, "key_a"), os.environ.get(ENV_BASE, "")
    if len(key.encode()) < _MIN_KEY or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", kid):
        raise _unconfigured()
    with _lock:
        built = _built.get((kid, key, base))
        if built is None:
            try:
                built = PlateDigestBuilder(
                    base_url=base, keys=KeyRing({kid: key.encode()}, active=kid), nonces=_nonce_store()
                )
            except ValueError:  # an unusable base URL
                raise _unconfigured() from None
            _built.clear()  # a changed key replaces the old builder; its nonces are the store's, not ours
            _built[(kid, key, base)] = built
        return built


def working_window() -> tuple[str, str]:
    """`working_window` of config/personal.yaml (local HH:MM, start inclusive, end exclusive); raises when unusable."""
    raw = yaml.safe_load(PERSONAL.read_text(encoding="utf-8"))["working_window"]
    start, end = raw["start"], raw["end"]
    if not (isinstance(start, str) and isinstance(end, str) and _HM.match(start) and _HM.match(end) and start < end):
        raise ValueError("working_window")
    return start, end


# -- applying a redeemed link ----------------------------------------------------------------------------------------


class _ViaLinkWriter:
    """The event writer with one more fact in the one-line summary: the change came from an email link (the event has
    no authn field and its data schema is closed, so the summary is where it is recorded)."""

    def __init__(self, inner: deps.EventWriter) -> None:
        self._inner = inner

    def append(self, world_id: str, event: dict[str, Any]) -> dict[str, Any]:
        summary = str(event.get("summary", "")).rstrip(".")
        return self._inner.append(world_id, {**event, "summary": f"{summary} (email link)."[:140]})


class PlateActions:
    """`PlateActionPort` over the people write path, as the redeemed person (authn "link"). `apply` is True only after
    the write committed and its `work_item.changed` was recorded in the person's Desk world (`Writer.commit` undoes
    the write when the event cannot be recorded), so a row moves only after its event (PE-30, HR-1). The owner check is
    `decide` inside the write; here the item must also be the person's own and still `open` (a Done link of an
    earlier mail never re-marks a done item); a Done and a Snooze racing for one item meet the store's
    compare-and-set, so one applies and the other is refused."""

    def __init__(self, stores: PeopleStores, now: str, events: WorkEvents) -> None:
        self._stores, self._now = stores, now
        self._events = WorkEvents(_ViaLinkWriter(events.writer), events.desks)

    def apply(self, user_id: str, item_id: str, action: str, *, authn: str) -> bool:
        stored = self._stores.work_items.get(deps.ORG_ID, item_id)
        if stored is None or stored.record["owner"] != user_id or stored.record["status"] != "open":
            return False
        writer = Writer(self._stores, deps.ORG_ID, user_id, self._now)
        writer.events = self._events
        try:
            if action == "done":
                people_items.done_item(writer, item_id)
            elif action == "snooze":
                people_items.snooze_item(writer, item_id, people_items.SnoozeIn(until=self._tomorrow(user_id)))
            else:
                return False
        except Refusal:  # not the person's own open item, a conflict, a refused write: nothing changed
            return False
        return True

    def _tomorrow(self, user_id: str) -> str:
        """Tomorrow at the start of the working window in the person's zone (BQ-PPL11C-28), as a UTC timestamp."""
        found = self._stores.persons.get(deps.ORG_ID, user_id)
        try:
            zone = ZoneInfo(found.record["time_zone"]) if found is not None else dt.UTC
        except Exception:
            zone = dt.UTC
        now = dt.datetime.fromisoformat(self._now.replace("Z", "+00:00")).astimezone(zone)
        hh, mm = working_window()[0].split(":")
        day = now.date() + dt.timedelta(days=1)
        until = dt.datetime(day.year, day.month, day.day, int(hh), int(mm), tzinfo=zone)
        return until.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# -- the routes ------------------------------------------------------------------------------------------------------

router = APIRouter()
_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "X-Robots-Tag": "noindex",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
    ),
}
_STYLE = "body{font:16px system-ui,sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem}button{font:inherit}"


def _page(status: int, text: str, button: str | None = None) -> HTMLResponse:
    form = f'<form method="post"><button type="submit">{button}</button></form>' if button else ""
    head = '<meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Tilo</title>'
    head += f"<style>{_STYLE}</style>"
    return HTMLResponse(f"<!doctype html>{head}<p>{text}</p>{form}", status_code=status, headers=_HEADERS)


@router.get("/l/{token}")
def confirm(
    token: str,
    builder: Annotated[PlateDigestBuilder, Depends(get_link_builder)],
    clock: Annotated[Any, Depends(deps.get_clock)],
) -> HTMLResponse:
    """The confirm page. Verifies, never consumes, never shows the item (the page is the same for any link)."""
    try:
        _item, option, _user = builder.peek(token, now=clock())
    except LinkRefused:
        return _page(404, _REFUSED)
    question, button = _PAGES[option]
    return _page(200, question, button)


@router.post("/l/{token}")
def redeem(
    token: str,
    builder: Annotated[PlateDigestBuilder, Depends(get_link_builder)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Any, Depends(deps.get_clock)],
    events: Annotated[WorkEvents, Depends(get_work_events)],
) -> HTMLResponse:
    now = clock()
    try:
        item, option, _user = builder.peek(token, now=now)
        port: PlateActionPort = PlateActions(stores, now, events)
        applied = builder.redeem_and_apply(token, item_id=item, option=option, port=port, now=now)
    except LinkRefused:
        return _page(410, _REFUSED)
    except Exception as exc:  # the store or the writer failed after the link was spent: never a 500, never a retry
        logger.warning("plate link not applied (%s)", type(exc).__name__)
        return _page(200, _UNAVAILABLE)  # 200 on purpose: a 5xx invites an automatic retry of a POST
    return _page(200, _DONE[option] if applied else _CANT)


# -- the daily trigger -----------------------------------------------------------------------------------------------


class PlateMailer(Protocol):
    def deliver(self, user_id: str, plate: dict[str, Any], *, now: str) -> bool:
        """Sends the person's plate digest once for the UTC day (the FR-CHN-18 policy and outbox path); True if sent."""
        ...


def get_plate_mailer(request: Request | None = None) -> PlateMailer:
    """The production mailer (FR-CHN-18b, FR-PA-06c, `plate_mailer.production_mailer`): the person's own standing L3
    rule, Desk-world artifact and events, own mailbox, outbox and the live Gmail stub. 503 `not_configured` while any
    seam is missing (no signing key, no store, no connector), so nothing is sent."""
    from tilo_api import plate_mailer  # noqa: PLC0415

    try:
        return plate_mailer.production_mailer({} if request is None else request.app.dependency_overrides)
    except Exception as exc:  # a missing seam raises its own 503 or NotConfigured: either way, nothing is sent
        if isinstance(exc, HTTPException):
            raise
        raise _unconfigured() from None


def _inside_window(now: str, zone_name: str, window: tuple[str, str]) -> bool:
    try:
        local = dt.datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(ZoneInfo(zone_name))
    except Exception:
        return False
    return window[0] <= f"{local:%H:%M}" < window[1]


def sweep(request: Request, now: str) -> int:
    """Once per tick: every person inside their window gets their plate handed to the mailer, which sends once per
    person per UTC day (its idempotency key). Off unless `TILO_PLATE_DIGEST=1`; a seam that is not wired, a person
    whose plate fails or a mailer that raises is logged by type and skipped; the tick's own answer never changes.
    The tick reads the process's own people store, never a demo session's, so a demo person is never mailed."""
    if os.environ.get(ENV_DIGEST) != "1":
        return 0
    overrides = request.app.dependency_overrides
    try:
        seam = overrides.get(get_plate_mailer, get_plate_mailer)
        mailer = seam(request) if inspect.signature(seam).parameters else seam()
        stores = overrides.get(deps.get_people_stores, deps.get_people_stores)()
        sources = overrides.get(deps.get_plate_sources, deps.get_plate_sources)()
        owners = overrides.get(deps.get_source_owners, deps.get_source_owners)()
        window = working_window()
        people = [s.record for s in stores.persons.list(deps.ORG_ID)][:MAX_PEOPLE]
    except Exception as exc:
        logger.info("plate digest not run (%s)", type(exc).__name__)
        return 0
    sent = 0
    for person in people:
        user = person["id"]
        if not _inside_window(now, str(person.get("time_zone")), window):
            continue
        try:
            plate = build_plate(stores, sources, owners, deps.ORG_ID, user, now)
            if plate is not None and plate["rows"] and mailer.deliver(user, plate, now=now):
                sent += 1
        except Exception as exc:
            logger.warning("plate digest failed for one person (%s)", type(exc).__name__)
    return sent
