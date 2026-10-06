"""Shared, non-test support for the FR-AGT-12 acceptance tests (independent Verifier, PRD 8.1, 8.6, 13.3).

THE INTERFACE THESE TESTS PIN (the PRD names no class; chosen here, logged as BQ-200 and BQ-201 in
docs/open-questions.md; a builder implements exactly this in `tilo_harness/verifier.py`):

    Deliverable(manifest, sources)          dataclass
        manifest   a provenance manifest (contracts/manifest.schema.json): its `claims` are what the
                   author says, `sources[].fingerprint` the SHA-256 of what was fetched.
        sources    Mapping[str, str]: source id -> the fetched text, as the raw archive holds it.

    Verifier(providers, *, agent_id, load=None)
        providers  Mapping[str, ModelProvider] keyed by role; the Verifier uses providers["verifier"] and
                   nothing else (PL-01, PRD 8.1 "checks independently of the author"). No "verifier"
                   entry: it refuses (raises) and never falls back to another role's provider.
        agent_id   the verifier-rank agent that signs the review (an `A_...` id in the layout).
        load       Callable[[artifact_ref], Deliverable] for review_and_record / run_plan. It may raise.

    await Verifier.review(deliverable) -> Review                 pure: writes no event
    await Verifier.review_and_record(ref, *, writer, cause=None, district=None) -> Review
        loads `ref`, reviews it and writes ONE `artifact.reviewed` (actor agent_id, target the artifact
        id, data {artifact, result}; trace.model_role is "verifier" when a model was called). A ref
        `load` cannot load is reviewed as `unverified`: a deliverable is never skipped.

    Review.result    "passed" | "failed" | "unverified"  (artifact.reviewed's result enum)
    Review.status    dict claim id -> "supported" | "contradicted" | "unverified"
    Review.manifest  the input manifest, unchanged except each claim's `verified`, recomputed: True iff the
                     Verifier found the claim supported. The author's own `verified` is never trusted.

    run_plan(..., verifier=Verifier(...))   (new optional keyword, default None = today's behaviour)
        After a successful unit's agent.handoff the executor calls verifier.review_and_record for every ref
        in the outcome's artifact_refs, with the handoff event as `cause`.

HOW A CLAIM IS JUDGED (BQ-200), in this order; the first rule that applies decides:
    1. no `source_ids`                                             -> unverified
    2. no cited source is usable (its text is missing from
       `sources`, or sha256(text) differs from its fingerprint)    -> unverified
    3. a number in the claim text appears in none of the usable
       cited sources' texts                                        -> contradicted (no model call needed)
    4. otherwise the `verifier`-role model decides, ONE call per claim (the prompt holds that claim's text and its
       usable sources' text, never the producer's identity, and never another claim). Its reply is the JSON object
       {"verdict": "supported" | "contradicted" | "cannot_tell"}; "supported" -> supported,
       "contradicted" -> contradicted, anything else (cannot_tell, unreadable reply, a raised
       provider error) -> unverified.
    result: every claim supported -> passed; any contradicted -> failed; otherwise unverified
    (a manifest with no claims is unverified, as manifest_appendix prints it, BQ-181).
A number is a run of digits, optionally with `,` thousands separators and one `.` decimal part, compared
without the commas. The model can only ever confirm what rules 1-3 left standing; it cannot undo them.

Like agt_support, `tilo_harness.verifier` does not exist yet: it is imported lazily, so this file always
imports and each test fails on the missing module (or behaviour) only.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from agt_scripted import ScriptedProvider, role_providers
from agt_support import assert_valid_contract

VERIFIER = "A_ver"
PRODUCER = "A_writer_p1"
PRODUCER_SKILL = "deck-writing"
PRODUCER_PROFILE = "flash-37"
LENIENT = json.dumps({"verdict": "supported"})  # a verifier model that approves whatever it is shown
FETCHED_AT = "2026-10-04T09:00:00.000Z"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _name(i: int) -> str:
    """A letters-only name unique per index (digits would add numbers to claim and source text)."""
    letters = "".join(chr(97 + (i // 26**k) % 26) for k in range(3))
    return f"Firm {letters.title()}"


def build_manifest(
    *,
    artifact_id: str,
    claims: list[dict[str, Any]],
    sources: dict[str, str],
    fingerprints: dict[str, str] | None = None,
    producer: str = PRODUCER,
) -> dict[str, Any]:
    """A manifest.schema.json-valid manifest. `fingerprints` overrides a source's recorded fingerprint text."""
    recorded = {sid: sha256_text(text) for sid, text in sources.items()}
    recorded.update({sid: sha256_text(text) for sid, text in (fingerprints or {}).items()})
    manifest = {
        "v": "1.0",
        "artifact": {"artifact_id": artifact_id, "version": 1},
        "content_sha256": sha256_text(artifact_id),
        "parents": [],
        "produced_by": {
            "agent_id": producer,
            "role": "writer",
            "skill": {"id": PRODUCER_SKILL, "version": "0.1.0"},
            "model_role": "writer",
            "profile": PRODUCER_PROFILE,
        },
        "inputs": [],
        "sources": [
            {
                "id": sid,
                "kind": "web",
                "ref": f"https://example.com/note-{index}",
                "fingerprint": f"sha256:{digest}",
                "fetched_at": FETCHED_AT,
            }
            for index, (sid, digest) in enumerate(sorted(recorded.items()))
        ],
        "claims": claims,
        "events": [],
        "authz": None,
    }
    assert_valid_contract("manifest", manifest)
    return manifest


def claim(claim_id: str, text: str, source_ids: list[str], *, verified: bool = False) -> dict[str, Any]:
    return {"id": claim_id, "location": "slide1/cell:B2", "text": text, "source_ids": source_ids, "verified": verified}


@dataclass(frozen=True)
class Case:
    case_id: str
    kind: str
    planted_false: bool
    deliverable: Any  # tilo_harness.verifier.Deliverable
    claim_id: str
    replies: dict[str, str | Exception]  # prompt substring -> verifier-model reply


def deliverable_of(manifest: dict[str, Any], sources: dict[str, str]) -> Any:
    from tilo_harness.verifier import Deliverable

    return Deliverable(manifest=manifest, sources=sources)


def note_for(i: int) -> str:
    return (
        f"Quarterly note {i}. {_name(i)} reported revenue of {40 + i} million "
        f"and {100 + 3 * i} new customers. The office moved in March."
    )


def _one(
    i: int, kind: str, text: str, *, planted_false: bool, source_ids=("src_a",), verified=False, sources=None, **extra
) -> Case:
    sources = {"src_a": note_for(i)} if sources is None else sources
    manifest = build_manifest(
        artifact_id=f"art_case_{i}",
        claims=[claim("cl_1", text, list(source_ids), verified=verified)],
        sources=sources if kind != "unknown_source" else {**sources, "src_ghost": f"original text {i}"},
        fingerprints=extra.get("fingerprints"),
    )
    held = {sid: txt for sid, txt in sources.items()}  # what the archive still holds
    return Case(f"case_{i}", kind, planted_false, deliverable_of(manifest, held), "cl_1", extra.get("replies", {}))


def planted_false_cases() -> list[Case]:
    """44 deliverables, each with one planted false claim. Every case's number is 900 + i (never in
    any source). 42 are decidable by the rules or by a model that says "contradicted" or nothing
    usable; 2 (`model_wrong`) are number-free claims that only the model could judge and the scripted
    model wrongly approves, so the honest catch rate is 42/44, not 100%."""
    cases: list[Case] = []
    i = 0

    def nxt() -> int:
        nonlocal i
        i += 1
        return i

    for _ in range(12):  # rule 3: wrong number against a usable source, model is lenient
        n = nxt()
        cases.append(
            _one(
                n,
                "number_mismatch",
                f"{_name(n)} reported revenue of {900 + n} million.",
                planted_false=True,
                source_ids=("src_a",),
            )
        )
    for _ in range(6):  # rule 2: cites a source whose text is not available
        n = nxt()
        cases.append(
            _one(
                n,
                "unknown_source",
                f"{_name(n)} reported revenue of {900 + n} million.",
                planted_false=True,
                source_ids=("src_ghost",),
            )
        )
    for _ in range(6):  # rule 2: the stored text no longer matches its fingerprint (edited after fetch)
        n = nxt()
        tampered = note_for(n).replace(f"{40 + n} million", f"{900 + n} million")
        cases.append(
            _one(
                n, "fingerprint_mismatch", f"{_name(n)} reported revenue of {900 + n} million.", planted_false=True,
                sources={"src_a": tampered}, fingerprints={"src_a": note_for(n)},
            )
        )  # fmt: skip
    for _ in range(6):  # rule 1: no source at all
        n = nxt()
        cases.append(
            _one(
                n, "no_sources", f"{_name(n)} reported revenue of {900 + n} million.", planted_false=True, source_ids=()
            )
        )
    for _ in range(6):  # the author says verified: true; rule 3 still catches it
        n = nxt()
        cases.append(
            _one(
                n,
                "self_verified_lie",
                f"{_name(n)} reported revenue of {900 + n} million.",
                planted_false=True,
                verified=True,
            )
        )
    for _ in range(4):  # rule 4: number-free, the model says contradicted
        n = nxt()
        text = f"{_name(n)} never moved its office."
        cases.append(
            _one(
                n,
                "textual_contradicted",
                text,
                planted_false=True,
                replies={text: json.dumps({"verdict": "contradicted"})},
            )
        )
    for lapse in (ValueError("provider timeout"), "I think this is probably fine"):  # rule 4: the model fails
        n = nxt()
        text = f"{_name(n)} never moved its office."
        cases.append(_one(n, "model_lapse", text, planted_false=True, replies={text: lapse}))
    for _ in range(2):  # rule 4: the scripted model wrongly approves a number-free false claim
        n = nxt()
        cases.append(_one(n, "model_wrong", f"{_name(n)} never moved its office.", planted_false=True))
    return cases


def true_cases() -> list[Case]:
    """20 deliverables with one TRUE claim each (10 with a number, 10 without); the Verifier must pass them,
    so a harness that marks everything unverified cannot reach the 90% by doing nothing."""
    cases: list[Case] = []
    for n in range(101, 111):
        cases.append(_one(n, "true_number", f"{_name(n)} reported revenue of {40 + n} million.", planted_false=False))
    for n in range(111, 121):
        cases.append(_one(n, "true_text", f"{_name(n)} moved its office in March.", planted_false=False))
    return cases


def verifier_model(cases: Iterable[Case], *, default: str | None = LENIENT) -> ScriptedProvider:
    replies: dict[str, str | Exception] = {}
    for case in cases:
        replies.update(case.replies)
    return ScriptedProvider(replies, default=default, profile_id="scripted-verifier")


def make_verifier(model: ScriptedProvider, *, agent_id: str = VERIFIER, load: Any = None, **other_roles: Any):
    from tilo_harness.verifier import Verifier

    providers = role_providers(verifier=model, **other_roles)
    return Verifier(providers, agent_id=agent_id, load=load), providers


def snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(manifest)
