"""The morning brief document, its storage and its email copy (ADR-0049, MO-08 to MO-10, MO-12): `make_brief` runs the
whole pipeline (reads, the one model call, the checks), stores the result as a version of the Desk-world artifact
`art_mbrief_<yyyymmdd>` and, for a scheduled brief with the email copy on, hands it to the owner-only digest path."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tilo_memory.artifacts import ArtifactError, ArtifactNotFound, ArtifactStore, NewVersion, Origin, Scope
from tilo_policy.schemas import conforms

from tilo_api import events as event_parts
from tilo_api.brief_store import KEEP_DAYS
from tilo_api.morning_brief import (
    MAX_MAIL,
    SCHEMA,
    Ctx,
    artifact_id,
    local_date,
    read_deadlines,
    read_mail,
    read_meetings,
)
from tilo_api.morning_brief_model import Picks, _offered, ask_model
from tilo_api.people_writes import Refusal

logger = logging.getLogger("tilo_api.morning_brief")
# -- the document (MO-08, MO-12) -------------------------------------------------------------------------------------


def assemble(
    ctx: Ctx, day: str, read: dict[str, Any], state: str, picks: Picks | None
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """(the brief, the mail the search returned by id). With the model used the mail section holds the picked mail
    (`ok`); otherwise the newest unread mail (`unsorted`), never presented as needing a reply."""
    meetings, mail, deadlines = read["meetings"], read["mail"], read["deadlines"]
    searched = {r["mail"]["source"]["id"]: r["mail"] for r in mail[1]}
    if state == "used" and picks is not None:
        shown = [r["mail"] for r in mail[1] if r["mail"]["source"]["id"] in picks.needs_reply]
        mail_status = mail[0]
    else:
        shown = [r["mail"] for r in mail[1] if r["unread"]][:MAX_MAIL]
        mail_status = "unsorted" if mail[0] == "ok" else mail[0]
    # the model's numbers count every offered mail (as `_prompt` numbered them), not only the ones shown
    table = {n: item["source"] for n, (_, item) in enumerate(_offered(meetings[1], mail[1], deadlines[1]), 1)}
    allowed = {item["source"]["id"] for item in shown} | {m["source"]["id"] for m in meetings[1]}
    allowed |= {d["source"]["id"] for d in deadlines[1]}
    suggestions, todos = [], []
    if state == "used" and picks is not None:
        for s in picks.suggestions:
            cites = [table[n] for n in s["numbers"]]
            if all(c["id"] in allowed for c in cites):
                suggestions.append({"text": s["text"], "cites": cites})
        if mail_status == "ok":
            todos = [{"title": t["title"], "due_text": t["due_text"], "mail": searched[t["id"]]} for t in picks.todos]
    doc = {
        "v": "1.0", "owner": ctx.user, "local_date": day, "time_zone": ctx.zone, "generated_at": ctx.now,
        "trigger": ctx.trigger, "model": state,
        "meetings": {"status": meetings[0], "items": meetings[1]},
        "mail_needing_reply": {"status": mail_status, "items": shown if mail_status in ("ok", "unsorted") else []},
        "deadlines": {"status": deadlines[0], "items": deadlines[1]},
        "suggestions": suggestions[:5], "todo_suggestions": todos[:5],
    }  # fmt: skip
    return doc, searched


def check(doc: dict[str, Any], searched: dict[str, dict[str, Any]]) -> bool:
    """The schema and MO-08: a cite names an item of this brief; a to-do's mail is one the search returned."""
    if not conforms(SCHEMA, doc):
        return False
    known = {
        (s["source"]["kind"], s["source"]["id"])
        for k in ("meetings", "mail_needing_reply", "deadlines")
        for s in doc[k]["items"]
    }
    cites = all((c["kind"], c["id"]) in known for s in doc["suggestions"] for c in s["cites"])
    return cites and all(searched.get(t["mail"]["source"]["id"]) == t["mail"] for t in doc["todo_suggestions"])


# -- storing (MO-09) -------------------------------------------------------------------------------------------------


def _scope(ctx: Ctx) -> tuple[Scope, str]:
    world = ctx.desks.desk_world(ctx.org, ctx.user)
    if ctx.desks.desk_owner(world) != ctx.user:
        raise Refusal(503, "not_configured")
    return Scope(ctx.org, world, ctx.user), world


def _delete(artifacts: ArtifactStore, scope: Scope, ref: dict[str, Any]) -> None:
    prefix = f"orgs/{scope.org_id}/worlds/{scope.world_id}/artifacts/{ref['artifact_id']}/versions"
    artifacts.retention().delete(f"{prefix}/{ref['version']:06d}")


def _announce(ctx: Ctx, world: str, kind: str, data: dict[str, Any]) -> None:
    part: dict[str, Any] = {
        "id": event_parts.new_part_id(), "type": kind, "actor": ctx.user if ctx.trigger == "on_demand" else "system",
        "target": ctx.user, "severity": "info", "summary": "Tilo made your morning brief.", "vis": [], "authz": None,
        "data": data,
    }  # fmt: skip
    for attempt in range(3):  # the same part id on each try: the single writer deduplicates it
        try:
            ctx.events.append(world, part)
            return
        except Exception:
            if attempt == 2:
                raise Refusal(503, "try_again") from None


def store(ctx: Ctx, doc: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """A new version of the day's artifact in the person's Desk world, announced. (the stored brief, whether the
    store's own screen called it clean). A version that was not announced is deleted."""
    scope, world = _scope(ctx)
    aid = artifact_id(doc["local_date"])
    try:
        parent = ctx.artifacts.versions(scope, aid)[-1].ref
    except ArtifactNotFound:
        parent = None
    run_id = "r_" + world[2:50]
    new = NewVersion("application/json", json.dumps(doc).encode(), run_id, Origin(kind="upload"), parent=parent)
    try:
        made = ctx.artifacts.with_new_id(lambda: aid).put(scope, new)
    except (ArtifactError, ValueError):
        raise Refusal(503, "try_again") from None
    announced = False
    try:
        if made.doc["screening"] != "clean":
            return doc, False
        if parent is None:
            data = {"artifact": made.ref} | {k: made.doc[k] for k in ("content_sha256", "media_type", "size_bytes")}
            _announce(ctx, world, "artifact.created", data)
        else:
            _announce(ctx, world, "artifact.versioned", {"artifact": made.ref, "previous_version": parent["version"]})
        announced = True
        return json.loads(ctx.artifacts.read(scope, made.ref)), True
    finally:
        if not announced:
            _delete(ctx.artifacts, scope, made.ref)


def read_latest(ctx_artifacts: ArtifactStore, desks: Any, org: str, user: str, day: str) -> dict[str, Any] | None:
    """MO-01, MO-09: the latest version for that local date from the person's own Desk world; None when there is no
    valid brief of theirs."""
    world = desks.desk_world(org, user)
    if desks.desk_owner(world) != user:
        return None
    scope = Scope(org, world, user)
    try:
        doc = json.loads(ctx_artifacts.read(scope, ctx_artifacts.versions(scope, artifact_id(day))[-1].ref))
    except (ArtifactError, ValueError, RecursionError):
        return None
    ok = isinstance(doc, dict) and conforms(SCHEMA, doc) and doc["owner"] == user and doc["local_date"] == day
    return doc if ok else None


def purge_old(artifacts: ArtifactStore, desks: Any, org: str, user: str, day: str) -> None:
    """MO-09: briefs older than `KEEP_DAYS` local days go (the week before that; the sweep runs this once a day)."""
    world = desks.desk_world(org, user)
    if desks.desk_owner(world) != user:
        return
    scope = Scope(org, world, user)
    for back in range(KEEP_DAYS + 1, KEEP_DAYS + 8):
        try:
            old = artifacts.versions(scope, artifact_id((date.fromisoformat(day) - timedelta(days=back)).isoformat()))
        except ArtifactNotFound:
            continue
        for version in old:
            _delete(artifacts, scope, version.ref)


# -- making one ------------------------------------------------------------------------------------------------------


def make_brief(ctx: Ctx, day: str | None = None) -> dict[str, Any]:
    """The whole brief for `day` (default: today in the person's zone), stored and returned. Raises `Refusal`
    (503 `try_again`) when it cannot be stored; the sections' own failures are statuses, never errors."""
    day = day or local_date(ctx.now, ctx.zone)
    _, world = _scope(ctx)
    read = {
        "meetings": read_meetings(ctx, world, day),
        "mail": read_mail(ctx, world),
        "deadlines": read_deadlines(ctx, day),
    }
    state, picks = ask_model(ctx, day, _offered(read["meetings"][1], read["mail"][1], read["deadlines"][1]))
    doc, searched = assemble(ctx, day, read, state, picks)
    if not check(doc, searched):  # MO-08: a brief that breaks it is not stored
        state, picks = "failed", None
        doc, searched = assemble(ctx, day, read, state, picks)
        if not check(doc, searched):
            raise Refusal(503, "try_again")
    stored, clean_verdict = store(ctx, doc)
    if not clean_verdict:  # the store's own screen flagged the bytes: keep only what code copied, flagged (MO-07)
        doc, searched = assemble(ctx, day, read, "flagged", None)
        stored, clean_verdict = store(ctx, doc)
        if not clean_verdict or not check(doc, searched):
            raise Refusal(503, "try_again")
    shown = [m["source"]["id"] for m in stored["mail_needing_reply"]["items"]]
    shown += [t["mail"]["source"]["id"] for t in stored["todo_suggestions"]]
    try:
        ctx.briefs.index_mail(ctx.org, ctx.user, list(dict.fromkeys(shown)), day)
    except Exception as exc:  # noqa: BLE001
        logger.warning("a brief's mail ids were not indexed (%s)", type(exc).__name__)
    if ctx.trigger == "schedule" and ctx.email_copy and ctx.mailer is not None:
        try:
            ctx.mailer.deliver_text(ctx.user, render_email(stored), now=ctx.now, kind="morning_brief")
        except Exception as exc:  # noqa: BLE001 - a failed or skipped send leaves the in-app brief as it is
            logger.warning("the brief email copy failed (%s)", type(exc).__name__)
    return stored


# -- the email copy (MO-10) ------------------------------------------------------------------------------------------

_SAY = {"not_connected": "not connected", "unavailable": "could not be read today"}


def render_email(doc: dict[str, Any]) -> str:
    """Plain text from the stored version: the three sections and the suggestions. No link and no address (every text
    was cleaned when the brief was made); a section that was not read says so."""
    out = [f"Your morning brief for {doc['local_date']}", ""]

    def section(title: str, block: dict[str, Any], line: Callable[[Any], str], empty: str, label: str = "") -> None:
        out.append(title + (f" ({label})" if label else ""))
        if block["status"] in _SAY:
            out.append(f"  This section {_SAY[block['status']]}.")
        out.extend(f"  - {line(i)}" for i in block["items"])
        if block["status"] in ("ok", "unsorted") and not block["items"]:
            out.append(f"  {empty}")
        out.append("")

    zone = ZoneInfo(doc["time_zone"])

    def when(m: dict[str, Any]) -> str:
        if m["all_day"]:
            return "all day"
        return datetime.fromisoformat(m["start"].replace("Z", "+00:00")).astimezone(zone).strftime("%H:%M")

    section("Meetings today", doc["meetings"], lambda m: f"{m['title']} ({when(m)})", "No meetings.")
    mail = doc["mail_needing_reply"]
    note = "unread, not sorted" if mail["status"] == "unsorted" else ""
    section("Mail", mail, lambda m: f"{m['from_name'] or 'Someone'}: {m['subject'] or '(no subject)'}", "None.", note)
    section("Deadlines", doc["deadlines"], lambda d: f"{d['title']} (due {d['due']})", "None.")
    if doc["suggestions"]:
        out += ["Suggestions", *(f"  - {s['text']}" for s in doc["suggestions"]), ""]
    return "\n".join(out).rstrip() + "\n"
