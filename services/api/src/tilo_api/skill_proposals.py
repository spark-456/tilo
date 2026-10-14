"""tilo_api.skill_proposals -- promote a Team Lead's answer into a proposed skill change (FR-AGT-15; PRD 8.2, 10.5).

The caller is the verified principal only; no body field names a proposer, reviewer, status or role. A Team Lead
counts only through a current record of `tilo_api.console.get_team_leads` (schema-valid, assigned by the world's
owner, not future-dated), read on every request. The Lead whose answer it is promotes it; the experts are the other
Team Leads of the skill's domain, never the proposer and never the owner as such (PRD 8.2: "the domain expert's
approval"). Only `SkillProposals.approve` writes skill files, and only for such an expert. No model is used here: the
rules are code. A principal of another world gets the 404 of an unknown world."""

from __future__ import annotations

import datetime
import functools
from collections.abc import Callable
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from tilo_harness.skill_proposals import SkillProposalError, SkillProposals
from tilo_harness.skills import SkillRegistry

from tilo_api import deps
from tilo_api.console import _assigned, get_team_leads

_STATUS = {
    "unknown_skill": 404,
    "unknown_proposal": 404,
    "not_the_answerer": 403,
    "not_team_lead_answer": 403,
    "self_review": 403,
    "not_expert": 403,
    "already_decided": 409,
    "stale": 409,
    "too_many_open": 409,
}


class DecisionStore(Protocol):
    def get(self, decision_id: str) -> dict | None: ...


def get_decision_store() -> DecisionStore:
    raise HTTPException(status_code=503, detail="not_configured")  # no Decision store is wired yet (BQ-AGT15-4)


@functools.cache
def get_skill_proposals() -> SkillProposals:
    """The process's proposal store over the repo's `skills/` folder (in memory, like the CardStore)."""
    return SkillProposals(SkillRegistry(deps._REPO_ROOT / "skills"))


class _Promote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    skill_id: str
    guidance: str | None = None


class _Approve(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Reject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _refused(error: SkillProposalError) -> JSONResponse:
    return JSONResponse(status_code=_STATUS.get(error.reason, 422), content={"error": error.reason})


def build_router(
    proposals: SkillProposals | Callable[..., SkillProposals], *, owner_of: Callable[[str], str | None]
) -> APIRouter:
    """`proposals` is one store, or a dependency that finds it; `owner_of(world_id)` is the world's owner."""
    router = APIRouter()
    get_proposals = (lambda: proposals) if isinstance(proposals, SkillProposals) else proposals

    def leads(principal: deps.Principal, world_id: str, records: list[dict]) -> list[dict]:
        """The caller's current Team Lead records; 404 for another world, 403 for anyone who holds none."""
        full = deps.full_world_session(principal)
        if principal.world_id != world_id and not full:
            raise HTTPException(status_code=404)
        owner, now = owner_of(world_id), _now()
        mine = [r for r in records if (full or principal.role == "team_lead") and r.get("user") == principal.user_id]
        current = [r for r in mine if _assigned(r, owner, now)]
        if not current:
            if principal.world_id != world_id and principal.user_id != owner:
                raise HTTPException(status_code=404)
            raise HTTPException(status_code=403)
        return current

    def reader_domains(principal: deps.Principal, world_id: str, records: list[dict]) -> set[str] | None:
        # Ownership grants visibility, never the domain expert's write authority.
        if deps.full_world_session(principal) and principal.role == "owner" and owner_of(world_id) == principal.user_id:
            return None
        return {r["domain"] for r in leads(principal, world_id, records)}

    def experts(world_id: str, domain: str, records: list[dict]) -> set[str]:
        owner, now = owner_of(world_id), _now()
        return {r["user"] for r in records if r.get("domain") == domain and _assigned(r, owner, now)}

    def visible(
        proposal: dict | None, principal: deps.Principal, domains: set[str] | None, world_id: str
    ) -> dict | None:
        """The proposal if it belongs to this world and the caller holds its domain or proposed it; else None."""
        if proposal is None or proposal["provenance"]["world_id"] != world_id:
            return None  # another world's proposal is never listed, shown or decided, whatever the domain slug
        mine = proposal["provenance"]["proposed_by"] == principal.user_id
        return proposal if domains is None or proposal["domain"] in domains or mine else None

    @router.post("/worlds/{world_id}/skill-proposals")
    def promote(
        world_id: str,
        body: _Promote,
        principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
        records: Annotated[list[dict], Depends(get_team_leads)],
        decisions: Annotated[DecisionStore, Depends(get_decision_store)],
        store: SkillProposals = Depends(get_proposals),  # a closure name: not resolvable inside Annotated
    ) -> JSONResponse:
        mine = leads(principal, world_id, records)
        decision: Any = decisions.get(body.decision_id)
        if not isinstance(decision, dict) or decision.get("source", {}).get("world_id") != world_id:
            raise HTTPException(status_code=404)  # unknown, or another world's: the same answer
        if decision.get("domain") not in {r["domain"] for r in mine}:
            raise HTTPException(status_code=403)
        try:
            made = store.propose(
                decision=decision, skill_id=body.skill_id, proposer=principal.user_id, guidance=body.guidance
            )
        except SkillProposalError as error:
            return _refused(error)
        return JSONResponse(status_code=201, content={"proposal": made})

    @router.get("/worlds/{world_id}/skill-proposals")
    def list_proposals(
        world_id: str,
        principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
        records: Annotated[list[dict], Depends(get_team_leads)],
        store: SkillProposals = Depends(get_proposals),  # a closure name: not resolvable inside Annotated
    ) -> dict[str, Any]:
        domains = reader_domains(principal, world_id, records)
        return {"proposals": [p for p in store.list() if visible(p, principal, domains, world_id)]}

    @router.get("/worlds/{world_id}/skill-proposals/{proposal_id}")
    def one(
        world_id: str,
        proposal_id: str,
        principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
        records: Annotated[list[dict], Depends(get_team_leads)],
        store: SkillProposals = Depends(get_proposals),  # a closure name: not resolvable inside Annotated
    ) -> dict[str, Any]:
        domains = reader_domains(principal, world_id, records)
        if (found := visible(store.get(proposal_id), principal, domains, world_id)) is None:
            raise HTTPException(status_code=404)
        return {"proposal": found}

    def decide(
        verb: str,
        world_id: str,
        proposal_id: str,
        principal: deps.Principal,
        records: list[dict],
        store: Any,
        **kw: Any,
    ) -> JSONResponse:
        domains = {r["domain"] for r in leads(principal, world_id, records)}
        found = visible(store.get(proposal_id), principal, domains, world_id)
        if found is None:
            raise HTTPException(status_code=404)
        try:
            done = getattr(store, verb)(
                proposal_id, reviewer=principal.user_id, experts=experts(world_id, found["domain"], records), **kw
            )
        except SkillProposalError as error:
            return _refused(error)
        return JSONResponse(status_code=200, content={"proposal": done})

    @router.post("/worlds/{world_id}/skill-proposals/{proposal_id}/approve")
    def approve(
        world_id: str,
        proposal_id: str,
        body: _Approve,
        principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
        records: Annotated[list[dict], Depends(get_team_leads)],
        store: SkillProposals = Depends(get_proposals),  # a closure name: not resolvable inside Annotated
    ) -> JSONResponse:
        return decide("approve", world_id, proposal_id, principal, records, store)

    @router.post("/worlds/{world_id}/skill-proposals/{proposal_id}/reject")
    def reject(
        world_id: str,
        proposal_id: str,
        body: _Reject,
        principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
        records: Annotated[list[dict], Depends(get_team_leads)],
        store: SkillProposals = Depends(get_proposals),  # a closure name: not resolvable inside Annotated
    ) -> JSONResponse:
        return decide("reject", world_id, proposal_id, principal, records, store, reason=body.reason)

    return router
