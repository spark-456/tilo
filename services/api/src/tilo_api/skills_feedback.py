"""Ratings, fixes and the state of a taught skill (FR-SKL-05, FR-SKL-06; ADR-0034, ADR-0037; taught_skill.rules.md
TS-08, TS-09, TS-11, TS-15).

`POST /v1/skills/{id}/runs/{run_id}/rating`, `POST /v1/skills/{id}/fixes`, `POST /v1/skills/{id}/state`. The person is
`Principal.user_id`, the org `deps.ORG_ID`; a body names neither, nor a version, nor a plan: a rating's version comes
from the recorded run, and the ledger (`skill_ledger.py`) checks the run's rater, outcome and version inside one write.
A fix and a state change are the owner's alone. Every refusal to read is the one 404 body. Each committed write adds one
event (ids, counts and enums only) in the acting person's Desk world after the record; its part id is stable, so a
retry after a failed event write adds the event once and changes nothing else. No model, no clock but the seam.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field, StrictBool
from tilo_people.stores import PeopleStores
from tilo_planning.artifacts import new_ulid

from tilo_api import deps
from tilo_api.people import _PeopleRoute
from tilo_api.people_events import WorkEvents, get_work_events
from tilo_api.people_writes import Writer, _Closed, json_body
from tilo_api.skill_ledger import SkillRefused
from tilo_api.skill_store import SkillStore
from tilo_api.skills_capture import _desk, _part
from tilo_api.skills_routes import _SKILL_ID, _guarded, _now, _teams, load_skill_config

router = APIRouter(route_class=_PeopleRoute)

_GONE = {"not_found": (404, "not_found"), "forbidden": (404, "not_found")}  # one body for every refusal to read
_FIX_REFUSALS = {**_GONE, "stale_version": (409, "version_conflict")}
_RATING_REFUSALS = {**_GONE, "already_rated": (409, "already_rated")}
_STATE_REFUSALS = {**_GONE, "not_enough_good_runs": (409, "not_enough_good_runs")}


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="not_found")


class RatingIn(_Closed):
    thumb: Literal["up", "down"]
    wrong_step: Annotated[int, Field(ge=1, le=20)] | None = None
    note: Annotated[str, Field(min_length=1, max_length=280)] | None = None


class FixIn(_Closed):
    from_version: Annotated[int, Field(ge=1)]
    step: Annotated[int, Field(ge=1, le=20)]
    text: Annotated[str, Field(min_length=1, max_length=280)]
    ask_first: StrictBool
    rating: Annotated[str, Field(min_length=1, max_length=26)] | None = None


class StateIn(_Closed):
    change: Literal["paused", "resumed", "learning", "trusted"]


def _refuse(
    refusal: SkillRefused, table: dict[str, tuple[int, str]], fallback: str = "invalid_record"
) -> HTTPException:
    status, detail = table.get(refusal.reason, (422, fallback))
    return HTTPException(status_code=status, detail=detail)


def _skill(store: SkillStore, teams: set[str], user: str, skill_id: str, *, owner_only: bool) -> dict[str, Any]:
    """The skill as the caller may read it (TS-01); a draft is the owner's working copy, never rated or fixed."""
    found = None if _SKILL_ID.fullmatch(skill_id) is None else store.get(deps.ORG_ID, skill_id)
    team = found is not None and found["scope"]["kind"] == "team" and found["scope"]["team"] in teams
    if found is None or found["status"] == "draft" or not (found["owner"] == user or (team and not owner_only)):
        raise _not_found()
    return found


def _event(we: WorkEvents, world: str, owner: str, kind: str, data: dict[str, Any], *key: str) -> None:
    summary = {
        "skill.rated": "A run was rated.",
        "skill.fixed": "A skill was fixed.",
        "skill.state_changed": "A skill changed.",
    }
    we.writer.append(world, _part(kind, owner, summary[kind], data, (data["skill"], *key), {}))


@router.post("/v1/skills/{skill_id}/runs/{run_id}/rating", status_code=201)
def rate_route(
    skill_id: str,
    run_id: str,
    body: Annotated[RatingIn, Depends(json_body(RatingIn))],
    response: Response,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[SkillStore, Depends(deps.get_skill_store)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    we: Annotated[WorkEvents, Depends(get_work_events)],
) -> dict[str, Any]:
    """The person's thumbs on one of their own finished runs of a skill they may read; one rating per run."""

    def save() -> dict[str, Any]:
        now, user = _now(clock), principal.user_id
        _skill(store, _teams(stores, user, now), user, skill_id, owner_only=False)
        run = store.get_real_run(deps.ORG_ID, skill_id, run_id)
        if run is None or run["by"] != user:
            raise _not_found()
        world = _desk(we, deps.ORG_ID, user)
        held = next((r for r in store.list_ratings(deps.ORG_ID, skill_id) if r["run_id"] == run_id), None)
        if held is not None:  # a retry of the same answer repeats its event; another answer is refused
            if (held["by"], held["thumb"], held["wrong_step"]) != (user, body.thumb, body.wrong_step):
                raise HTTPException(status_code=409, detail="already_rated")
            response.status_code, rating = 200, held
        else:
            note = None if body.note is None else Writer(stores, deps.ORG_ID, user, now, redact).text(body.note)
            rating = {
                "id": new_ulid(),
                "skill": skill_id,
                "version": run["version"],
                "run_id": run_id,
                "by": user,
                "thumb": body.thumb,
                "wrong_step": body.wrong_step,
                "note": note,
                "at": now,
            }
            try:
                store.record_rating(deps.ORG_ID, skill_id, rating)
            except SkillRefused as refusal:
                raise _refuse(refusal, _RATING_REFUSALS) from None
        data = {k: rating[k] for k in ("skill", "version", "run_id", "thumb", "wrong_step")}
        _event(we, world, user, "skill.rated", data, "rated", run_id)
        return rating  # type: ignore[no-any-return]

    return _guarded(save)


@router.post("/v1/skills/{skill_id}/fixes")
def fix_route(
    skill_id: str,
    body: Annotated[FixIn, Depends(json_body(FixIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[SkillStore, Depends(deps.get_skill_store)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    we: Annotated[WorkEvents, Depends(get_work_events)],
) -> dict[str, Any]:
    """The owner's fix of one step of the current version: text and Ask me first, version + 1 (TS-09)."""

    def save() -> dict[str, Any]:
        now, owner = _now(clock), principal.user_id
        skill = _skill(store, _teams(stores, owner, now), owner, skill_id, owner_only=True)
        text = Writer(stores, deps.ORG_ID, owner, now, redact).text(body.text)
        world = _desk(we, deps.ORG_ID, owner)
        for done in store.list_fixes(deps.ORG_ID, skill_id):  # the same fix of the same version is a retry
            if (done["from_version"], done["step"], done["text"], done["ask_first"]) == (
                body.from_version,
                body.step,
                text,
                body.ask_first,
            ):
                after, fix_id, to_version = skill, done["id"], done["to_version"]
                break
        else:
            fix = {
                "id": new_ulid(),
                "from_version": body.from_version,
                "step": body.step,
                "text": text,
                "ask_first": body.ask_first,
                "by": owner,
                "rating": body.rating,
                "at": now,
            }
            try:
                after = store.apply_fix(deps.ORG_ID, skill_id, fix)
            except SkillRefused as refusal:
                raise _refuse(refusal, _FIX_REFUSALS, "invalid_fix") from None
            fix_id, to_version = fix["id"], after["version"]
        data = {"skill": skill_id, "from_version": body.from_version, "to_version": to_version, "step": body.step}
        _event(we, world, owner, "skill.fixed", data, "fixed", fix_id)
        return after  # type: ignore[no-any-return]

    return _guarded(save)


@router.post("/v1/skills/{skill_id}/state")
def state_route(
    skill_id: str,
    body: Annotated[StateIn, Depends(json_body(StateIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[SkillStore, Depends(deps.get_skill_store)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    we: Annotated[WorkEvents, Depends(get_work_events)],
) -> dict[str, Any]:
    """The owner pauses, resumes, keeps learning or marks the skill trusted (verified up-rated runs, TS-08)."""

    def save() -> dict[str, Any]:
        now, owner = _now(clock), principal.user_id
        _skill(store, _teams(stores, owner, now), owner, skill_id, owner_only=True)
        world, threshold = _desk(we, deps.ORG_ID, owner), load_skill_config().good_runs
        try:
            after, changed = store.set_state(deps.ORG_ID, skill_id, body.change, by=owner, threshold=threshold, now=now)
        except SkillRefused as refusal:
            raise _refuse(refusal, _STATE_REFUSALS) from None
        if changed:
            data = {
                "skill": skill_id,
                "version": after["version"],
                "change": body.change,
                "good_runs": after["good_runs"],
                "threshold": threshold if body.change == "trusted" else None,
            }
            _event(we, world, owner, "skill.state_changed", data, "state", body.change, after["updated_at"])
        return after  # type: ignore[no-any-return]

    return _guarded(save)
