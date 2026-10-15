"""ADR-0046 signed, single-use team invite links (SELF-SERVE-TEAMS)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from tilo_people.directory import Directory
from tilo_people.errors import AlreadyExists, VersionConflict
from tilo_people.stores import PeopleStores
from tilo_people.teams import LinkRequest, decide_link

from tilo_api import deps, events
from tilo_api.invite_link_store import get_links
from tilo_api.people import _PeopleRoute
from tilo_api.people_teams import _session, _snapshot, _team
from tilo_api.people_writes import Empty, Refusal, _Closed, json_body

router = APIRouter(route_class=_PeopleRoute)
Principal = Annotated[deps.Principal, Depends(deps.get_current_principal)]
Stores = Annotated[PeopleStores, Depends(deps.get_people_stores)]
Clock = Annotated[Callable[[], str], Depends(deps.get_clock)]
Writer = Annotated[deps.EventWriter, Depends(deps.get_event_writer)]
Desks = Annotated[deps.DeskWorlds, Depends(deps.get_desk_worlds)]
_TOKEN = re.compile(r"v1\.([A-Za-z0-9_-]{1,32})\.(til_[0-9a-f]{24})\.([A-Za-z0-9_-]{43})\.([A-Za-z0-9_-]{43})")
_KID = re.compile(r"[A-Za-z0-9_-]{1,32}")
_ID = re.compile(r"til_[0-9a-f]{24}")
_DOMAIN = b"tilo.team-invite-link.v1\x00"
_UNAVAILABLE = Refusal(404, "invite_unavailable")


class AcceptIn(_Closed):
    token: str


def _key() -> tuple[str, bytes]:
    kid = os.environ.get("TILO_INVITE_LINK_KEY_ID", "key_a")
    key = os.environ.get("TILO_INVITE_LINK_KEY", "").encode()
    if len(key) < 32 or _KID.fullmatch(kid) is None:
        raise Refusal(503, "not_configured")
    return kid, key


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes | None:
    try:
        raw = base64.urlsafe_b64decode(value + "=")
        return raw if _b64(raw) == value and len(raw) == 32 else None
    except (ValueError, binascii.Error):
        return None


def _sign(kid: str, key: bytes, invite_id: str, nonce: bytes) -> str:
    stem = f"v1.{kid}.{invite_id}.{_b64(nonce)}"
    return f"{stem}.{_b64(hmac.digest(key, _DOMAIN + stem.encode('ascii'), 'sha256'))}"


def _parse(token: str, kid: str, key: bytes) -> tuple[str, str] | None:
    if len(token) > 200 or (match := _TOKEN.fullmatch(token)) is None:
        return None
    given_kid, invite_id, nonce_text, signature = match.groups()
    nonce, sig = _unb64(nonce_text), _unb64(signature)
    if given_kid != kid or nonce is None or sig is None:
        return None
    expected = hmac.digest(key, _DOMAIN + token.rsplit(".", 1)[0].encode("ascii"), "sha256")
    if not hmac.compare_digest(sig, expected):
        return None
    return invite_id, hashlib.sha256(nonce).hexdigest()


def _links(stores: PeopleStores) -> Any:
    try:
        return get_links(stores)
    except NotImplementedError:
        raise Refusal(503, "not_configured") from None
    except Exception:
        raise Refusal(503, "unavailable") from None


def _snapshot_links(store: Any) -> list[dict[str, Any]]:
    try:
        return [dict(row.record) for row in store.list(deps.ORG_ID)]
    except Exception:
        raise Refusal(503, "unavailable") from None


def _manages(d: Directory, actor: str, team: str, now: str) -> bool:
    me = d.record(actor)
    return me is not None and (me["org_role"] == "owner" or d.is_lead(actor, team, now))


def _event(
    writer: deps.EventWriter,
    desks: deps.DeskWorlds,
    actor: str,
    kind: str,
    invite_id: str,
    team: str,
    expires_at: str | None = None,
) -> None:
    world = desks.desk_world(deps.ORG_ID, actor)
    if not (
        isinstance(world, str)
        and re.fullmatch(r"w_desk_[0-9A-Za-z_]{1,43}", world)
        and desks.desk_owner(world) == actor
    ):
        raise ValueError("Desk unavailable")
    data = {"invite_id": invite_id, "team": team}
    if expires_at is not None:
        data["expires_at"] = expires_at
    writer.append(
        world,
        {
            "id": events.stable_part_id(kind, invite_id),
            "type": kind,
            "actor": actor,
            "target": actor,
            "summary": "A team invite link changed.",
            "vis": [],
            "authz": None,
            "data": data,
        },
    )


@router.post("/v1/teams/{team}/invite-links", status_code=201)
def make_link(
    team: str,
    empty: Annotated[Empty, Depends(json_body(Empty))],
    principal: Principal,
    stores: Stores,
    clock: Clock,
    writer: Writer,
    desks: Desks,
) -> dict[str, str]:
    _session(principal)
    team, now = _team(team), clock()
    d, _ = _snapshot(stores)
    if not _manages(d, principal.user_id, team, now):
        raise Refusal(403, "forbidden")
    kid, key = _key()
    store = _links(stores)
    links = _snapshot_links(store)
    if (
        sum(1 for link in links if link["team"] == team and link["status"] == "pending" and now < link["expires_at"])
        >= 10
    ):
        raise Refusal(429, "too_many_links")
    latest = [
        m["assigned_by"]["at"]
        for p in d.persons.values()
        for m in p["memberships"]
        if m["team"] == team and m.get("lead") is True
    ]
    if any(at >= now for at in latest):
        raise Refusal(409, "retry")
    invite_id, nonce = "til_" + secrets.token_hex(12), secrets.token_bytes(32)
    expires = (datetime.strptime(now, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC) + timedelta(days=7)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"
    record = {
        "id": invite_id,
        "org_id": deps.ORG_ID,
        "team": team,
        "created_by": {"by": principal.user_id, "at": now},
        "expires_at": expires,
        "key_id": kid,
        "nonce_sha256": hashlib.sha256(nonce).hexdigest(),
        "status": "pending",
        "redeemed": None,
        "revoked": None,
    }
    asked = LinkRequest(principal.user_id, "create_link", deps.ORG_ID, now, team=team, record=record)
    if not decide_link(asked, d, links):
        raise Refusal(403, "forbidden")
    try:
        saved = store.create(record)
    except AlreadyExists:
        raise Refusal(409, "retry") from None
    except Exception:
        raise Refusal(503, "unavailable") from None
    try:
        _event(writer, desks, principal.user_id, "invite_link.created", invite_id, team, expires)
    except Exception:
        try:
            store.delete(deps.ORG_ID, invite_id, saved.version)
        except Exception:
            pass
        raise Refusal(503, "unavailable") from None
    return {"invite_id": invite_id, "token": _sign(kid, key, invite_id, nonce), "expires_at": expires}


@router.get("/v1/teams/{team}/invite-links")
def list_links(team: str, principal: Principal, stores: Stores, clock: Clock) -> list[dict[str, str]]:
    _session(principal)
    team, now = _team(team), clock()
    d, _ = _snapshot(stores)
    if not _manages(d, principal.user_id, team, now):
        raise Refusal(403, "forbidden")
    states = {"redeemed": "used", "revoked": "withdrawn"}
    return [
        {
            "id": row["id"],
            "created_at": row["created_by"]["at"],
            "expires_at": row["expires_at"],
            "state": states.get(row["status"], "unused" if now < row["expires_at"] else "expired"),
        }
        for row in _snapshot_links(_links(stores))
        if row["team"] == team
    ]


@router.post("/v1/teams/{team}/invite-links/{invite_id}/revoke")
def revoke_link(
    team: str,
    invite_id: str,
    empty: Annotated[Empty, Depends(json_body(Empty))],
    principal: Principal,
    stores: Stores,
    clock: Clock,
    writer: Writer,
    desks: Desks,
) -> dict[str, str]:
    _session(principal)
    team, now = _team(team), clock()
    d, _ = _snapshot(stores)
    if not _manages(d, principal.user_id, team, now):
        raise Refusal(403, "forbidden")
    store = _links(stores)
    if _ID.fullmatch(invite_id) is None:
        return {"status": "done"}
    try:
        row = store.get(deps.ORG_ID, invite_id)
        if row is None or row.record["team"] != team:
            return {"status": "done"}
        if row.record["status"] == "pending":
            asked = LinkRequest(principal.user_id, "revoke_link", deps.ORG_ID, now, team=team, link=invite_id)
            if decide_link(asked, d, [row.record]):
                changed = {**row.record, "status": "revoked", "revoked": {"by": principal.user_id, "at": now}}
                store.replace(changed, row.version)
                row = store.get(deps.ORG_ID, invite_id)
        if row is not None and row.record["status"] == "revoked":
            _event(writer, desks, row.record["revoked"]["by"], "invite_link.revoked", invite_id, team)
    except VersionConflict:
        pass
    except Exception:
        raise Refusal(503, "unavailable") from None
    return {"status": "done"}


@router.post("/v1/team-invite-links/accept")
def accept_link(
    body: Annotated[AcceptIn, Depends(json_body(AcceptIn))],
    principal: Principal,
    stores: Stores,
    clock: Clock,
    writer: Writer,
    desks: Desks,
) -> dict[str, str]:
    _session(principal)
    if principal.verified_email is None:
        raise Refusal(403, "forbidden")
    kid, key = _key()
    parsed = _parse(body.token, kid, key)
    if parsed is None:
        raise _UNAVAILABLE
    invite_id, digest = parsed
    store = _links(stores)
    now = clock()
    try:
        row = store.get(deps.ORG_ID, invite_id)
        d, _ = _snapshot(stores)
        if row is None or not hmac.compare_digest(digest, row.record["nonce_sha256"]) or row.record["key_id"] != kid:
            raise _UNAVAILABLE
        asked = LinkRequest(
            principal.user_id,
            "redeem_link",
            deps.ORG_ID,
            now,
            link=invite_id,
            nonce_sha256=digest,
            verified_email=principal.verified_email,
        )
        if not decide_link(asked, d, [row.record]):
            me = d.record(principal.user_id)
            if (
                me is not None
                and len(me["memberships"]) >= 8
                and all(m["team"] != row.record["team"] for m in me["memberships"])
            ):
                reduced = Directory.of(
                    [
                        *([p for uid, p in d.persons.items() if uid != principal.user_id]),
                        {**me, "memberships": me["memberships"][:-1]},
                    ]
                )
                if decide_link(asked, reduced, [row.record]):
                    raise Refusal(409, "membership_limit")
            raise _UNAVAILABLE
        claimed = {**row.record, "status": "redeemed", "redeemed": {"by": principal.user_id, "at": now}}
        try:
            store.replace(claimed, row.version)
        except VersionConflict:
            raise _UNAVAILABLE from None
    except Refusal:
        raise
    except Exception:
        raise Refusal(503, "unavailable") from None
    entry = {"team": row.record["team"], "assigned_by": row.record["created_by"], "accepted_at": now}
    written_version: int | None = None
    try:
        for _ in range(3):
            fresh, rows = _snapshot(stores)
            if not decide_link(asked, fresh, [row.record]):
                break
            person = rows[principal.user_id]
            after = {**person.record, "memberships": [*person.record["memberships"], entry]}
            try:
                updated = stores.persons.replace(after, expected_version=person.version)
                written_version = updated.version
                break
            except VersionConflict:
                continue
        if written_version is None:
            raise ValueError("membership changed")
        _event(writer, desks, principal.user_id, "invite_link.accepted", invite_id, row.record["team"])
    except Exception:
        if written_version is not None:
            for _ in range(3):
                try:
                    current = stores.persons.get(deps.ORG_ID, principal.user_id)
                    if current is None or entry not in current.record["memberships"]:
                        break
                    remaining = [m for m in current.record["memberships"] if m != entry]
                    stores.persons.replace(
                        {**current.record, "memberships": remaining}, expected_version=current.version
                    )
                    break
                except VersionConflict:
                    continue
                except Exception:
                    break
        raise Refusal(503, "unavailable") from None
    return {"team": row.record["team"], "state": "member"}
