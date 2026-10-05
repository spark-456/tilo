"""Doubles, oracles and data factories for the FR-CON-16, FR-CON-17 and FR-CON-20 tests
(build handoff, Lovable link route, granted data). Pinned API: API_FR_CON_16_17_20.md.

No production code (root CLAUDE.md test-writer rule). Everything here is either a test double that
the API doc says the tests supply (the `TextArtifacts` read side, the `Screen`, the redactor), a
contract-shaped literal, or an *oracle*: a few lines that restate a formula the API doc pins
(`render_prompt`, `exact`, the BriefTooLong message, `link_length`) so a test can compare the
builder's output with the documented formula rather than with the builder's own helper.

`tilo_connectors.handoff`, `.grants` and `.adapters.lovable` do not exist yet; the tests import
them lazily through the `h()`, `g()` and `lv()` accessors, so a missing module fails the test that
needs it with ModuleNotFoundError, never a collection error in this file.

Fake secrets are assembled at runtime (root CLAUDE.md hard rule): nothing secret-looking is in
this file's text.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import itertools
import json
import pathlib
import re
import threading
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import yaml
from _connectors_lib import OWNER, RUN, WORLD, ManualClock
from conftest import gate_case

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CONFIG = REPO_ROOT / "config"
CONTRACTS = REPO_ROOT / "contracts"
SRC = REPO_ROOT / "services" / "connectors" / "src" / "tilo_connectors"

ORG = "org_example"
UNIT = "U7"
AGENT = "A_writer1"
ATTEMPT = 1
STRANGER = "u_stranger"
APPROVER = "u_approver"
T0 = "2026-10-05T09:30:00.000Z"
T1 = "2026-10-05T09:45:00.000Z"
LINK_PREFIX = "https://lovable.dev/#prompt="


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def schema_registry():
    """A referencing Registry over every contracts/**/*.schema.json, keyed by $id (as conftest.build_registry)."""
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    resources = []
    for path in sorted(CONTRACTS.glob("**/*.schema.json")):
        data = load_json(path)
        resources.append(
            (
                data.get("$id") or path.resolve().as_uri(),
                Resource.from_contents(data, default_specification=DRAFT202012),
            )
        )
    return Registry().with_resources(resources)


def h():
    return importlib.import_module("tilo_connectors.handoff")


def g():
    return importlib.import_module("tilo_connectors.grants")


def lv():
    return importlib.import_module("tilo_connectors.adapters.lovable")


def errs():
    return importlib.import_module("tilo_connectors.errors")


# ---------------------------------------------------------------------------
# Fake secrets, redactor, safety screen


def fake_secret(salt: int = 0) -> str:
    """A GitHub-style token shape assembled at runtime; never a real value."""
    return "gh" + "p_" + "".join(chr(ord("A") + (i * 7 + salt) % 26) for i in range(36))


def make_redact(*secrets: str):
    """The injected SEC-01 redactor: replaces each secret with a marker."""

    def redact(text: str) -> str:
        for s in secrets:
            text = text.replace(s, "[REDACTED]")
        return text

    return redact


def raising_redact(text: str) -> str:
    raise RuntimeError("redactor is down")


def empty_redact(text: str) -> str:
    return ""


class FakeSafety:
    """A `Screen`: flags any text holding a trigger, records every text it was asked about."""

    def __init__(self, flag_if: tuple[str, ...] = (), raises: bool = False) -> None:
        self.flag_if = tuple(flag_if)
        self.raises = raises
        self.calls: list[str] = []

    def check(self, text: str) -> dict:
        self.calls.append(text)
        if self.raises:
            raise RuntimeError("safety screen is down")
        flagged = any(t in text for t in self.flag_if)
        return {"flagged": flagged, "reason": "test trigger" if flagged else None}


# ---------------------------------------------------------------------------
# Config and registry


def default_partner_yaml() -> dict:
    return yaml.safe_load((CONFIG / "build_partners.yaml").read_text(encoding="utf-8"))


def write_partners(tmp_path: pathlib.Path, *, raw: Any = None, name: str = "build_partners.yaml", **limits: Any):
    """A build_partners.yaml in tmp_path: the shipped one with `limits` set on the lovable partner."""
    data = raw if raw is not None else default_partner_yaml()
    if raw is None:
        if "max_prompt_chars" in limits and "max_excerpt_chars" not in limits:
            limits["max_excerpt_chars"] = min(4000, limits["max_prompt_chars"])
        data["partners"]["lovable"].update(limits)
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def registry():
    from tilo_connectors.registry import load_registry

    return load_registry(CONFIG / "connectors.yaml")


def declaration() -> dict:
    return copy.deepcopy(dict(registry().get("lovable")))


def load_partner(path: Any = None):
    kwargs = {"registry": registry()}
    return h().load_build_partners(path if path is not None else h().DEFAULT_BUILD_PARTNERS, **kwargs)


def partner(tmp_path: pathlib.Path | None = None, **limits: Any):
    """The lovable BuildPartnerConfig, from the shipped file or (with limits) a test config file."""
    if not limits:
        return load_partner()["lovable"]
    assert tmp_path is not None, "limits need a tmp_path to write the test config file"
    return load_partner(write_partners(tmp_path, **limits))["lovable"]


# ---------------------------------------------------------------------------
# Texts: what the owner accepted, and what they did not (planted canaries)

PLANT = {
    "draft_goal": "Sell scooter batteries through a loyalty quokka marketplace",
    "draft_title": "Marketplace portal",
    "removed_constraint": "Accept pangolin vouchers at checkout",
    "other_summary": "Rebuild everything on a mainframe emulator with punch cards",
    "other_label": "Mainframe rewrite",
    "thread": "Hector said to ring 5550199 about the walrus discount",
    "preference": "Use the narwhal colour palette",
    "source_label": "Confidential supplier quotes zebra ledger",
    "risk": "Checkout may leak the zebra ledger",
    "ungranted": "Zorblax passphrase hunters ledger",
    "draft_audience": "Venture capitalists at the gryphon summit",
}
GOOD_FRAMING = "Build the Storefront website described below. Follow the requirements exactly and add nothing else."


def approved_brief(**over: Any) -> dict:
    brief = {
        "goal": "Build a storefront website for a scooter battery shop.",
        "deliverables": [{"title": "Storefront website", "format": "in_app"}],
        "audience": "Small business owners buying battery packs",
        "deadline": "2026-10-09",
        "constraints": ["Show prices in rupees", "Works on a phone"],
        "sources": [{"kind": "file", "ref": "art_quote_a", "label": PLANT["source_label"]}],
        "sensitivity": "business",
        "assumptions": [{"question": "Which language?", "assumed": "One language: English"}],
        "applied_preferences": [
            {
                "field": "constraints",
                "value": PLANT["preference"],
                "citation": {"kind": "preference", "ref": "mem_palette", "recorded_at": T0},
            }
        ],
    }
    brief.update(over)
    return brief


def draft_brief() -> dict:
    """What the Director first proposed; the owner changed the goal, the audience and the deliverable
    title and removed a constraint before approving."""
    brief = approved_brief()
    brief["goal"] = PLANT["draft_goal"]
    brief["audience"] = PLANT["draft_audience"]
    brief["deliverables"] = [{"title": PLANT["draft_title"], "format": "in_app"}]
    brief["constraints"] = ["Show prices in rupees", "Works on a phone", PLANT["removed_constraint"]]
    return brief


def _plan_approaches() -> list[dict]:
    plan = load_json(CONTRACTS / "fixtures" / "plan" / "valid" / "three_approaches_policy_gate.json")
    return copy.deepcopy(plan["approaches"])


def approaches() -> list[dict]:
    """Two approaches: `balanced` (the owner's pick) and `ambitious` (not picked)."""
    base = _plan_approaches()
    chosen = next(a for a in base if a["id"] == "balanced")
    other = next(a for a in base if a["id"] == "thorough")
    chosen.update(
        label="Balanced build",
        summary="A clean storefront with product pages and a cart.",
        skips=["Admin dashboard"],
        risks=[PLANT["risk"]],
    )
    other.update(id="ambitious", label=PLANT["other_label"], summary=PLANT["other_summary"], skips=[])
    return [other, chosen]


def accept(**over: Any):
    """accepted_requirements(...) for the standard inputs; `over` replaces any keyword."""
    approach_list = over.pop("approach_list", None) or approaches()
    chosen_id = over.pop("chosen_approach_id", "balanced")
    approach = (
        next(a for a in approach_list if a["id"] == chosen_id) if "approach" not in over else over.pop("approach")
    )
    kwargs: dict[str, Any] = {
        "world_id": WORLD,
        "run_id": RUN,
        "world_owner": OWNER,
        "brief": approved_brief(),
        "approach": approach,
        "chosen_approach_id": chosen_id,
        "deliverable_index": 0,
        "approval": {"by": "person", "ref": OWNER, "at": T0},
    }
    kwargs.update(over)
    return h().accepted_requirements(**kwargs)


def declined(**over: Any) -> tuple[str, ...]:
    kwargs: dict[str, Any] = {
        "draft_brief": draft_brief(),
        "approved_brief": approved_brief(),
        "approaches": approaches(),
        "chosen_approach_id": "balanced",
    }
    kwargs.update(over)
    return h().declined_texts(**kwargs)


def planted_unaccepted() -> list[str]:
    """Texts the owner did not accept, plus the one that was never passed to any function."""
    return [
        PLANT["draft_goal"],
        PLANT["removed_constraint"],
        PLANT["other_summary"],
        PLANT["thread"],
        PLANT["preference"],
        PLANT["source_label"],
        PLANT["risk"],
        PLANT["draft_title"],
        PLANT["draft_audience"],
    ]


# ---------------------------------------------------------------------------
# Oracles: the formulas the API doc pins


def collapse(value: str) -> str:
    return " ".join(value.split())


def fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def oracle_requirements_block(a: Any) -> str:
    lines = [
        "## Goal",
        a.goal,
        "",
        "## Deliverable",
        a.deliverable_title,
        "",
        "## Audience",
        a.audience,
        "",
        "## Approach",
        f"{a.approach_label}: {a.approach_summary}",
    ]
    if a.constraints:
        lines += ["", "## Requirements", *(f"- {c}" for c in a.constraints)]
    if a.assumptions:
        lines += ["", "## Assumptions", *(f"- {x}" for x in a.assumptions)]
    if a.skips:
        lines += ["", "## Leave out", *(f"- {s}" for s in a.skips)]
    return "\n".join(lines) + "\n"


def oracle_prompt(a: Any, framing: str, excerpts: Any = ()) -> str:
    block = oracle_requirements_block(a)
    reference = ""
    if excerpts:
        lines = ["## Reference material", "The client shared these excerpts as reference material."]
        for e in excerpts:
            lines += ["", f"### {collapse(e.item.label)}", fence(e.text), e.text, fence(e.text)]
        reference = "\n" + "\n".join(lines) + "\n"
    return framing + "\n\n" + block + reference


def default_framing(a: Any) -> str:
    return h().DEFAULT_FRAMING.format(title=a.deliverable_title)


def oracle_link(prompt: str) -> str:
    return LINK_PREFIX + quote(prompt, safe="")


def oracle_exact(prompt: str, items: tuple[tuple[str, int], ...], name: str = "Lovable") -> str:
    k = len(items)
    if items:
        listed = ", ".join(f"{a}@{v}" for a, v in items)
        carries = f"It carries excerpts of {k} granted item{'s' if k != 1 else ''}: {listed}."
    else:
        carries = "It carries no granted data."
    return (
        f"Makes a {name} build link from the prompt shown ({len(prompt):,} characters). {carries} "
        f"Nothing leaves Tilo until you open the link; {name} starts building only when you press send there."
    )


def oracle_too_long_message(prompt_chars: int, link_len: int, max_chars: int, max_url: int) -> str:
    return (
        f"This brief is too long for a Lovable link: the prompt is {prompt_chars:,} characters "
        f"(at most {max_chars:,}) and the link would be {link_len:,} characters (at most {max_url:,}). "
        "Nothing was cut and nothing was sent. Lovable's connected route can take longer briefs, "
        "but it is not available yet."
    )


def link_record_bytes(url: str, prompt_ref: dict, outbox_id: str) -> bytes:
    return json.dumps(
        {
            "v": "1.0",
            "partner": "lovable",
            "route": "link",
            "url": url,
            "prompt": {"artifact_id": prompt_ref["artifact_id"], "version": prompt_ref["version"]},
            "outbox_id": outbox_id,
            "project_id": None,
            "status": "link_ready",
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def sized_text(n: int) -> str:
    """Exactly n characters (n >= 7) of whole words, every one in the shipped `framing_words`."""
    k = (n + 1) // 4  # k words of "the" and single spaces are 4k - 1 characters
    rest = n - (4 * k - 1)
    if rest == 1:
        k -= 1
        rest += 4
    base = " ".join(["the"] * k)
    if rest == 0:
        return base
    filler = {2: "a", 3: "an", 4: "the", 5: "this"}[rest]
    return base + " " + filler


# ---------------------------------------------------------------------------
# The TextArtifacts double (P7's ArtifactStore read side, scoped by world; logs every read)


class FakeTextArtifacts:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str, int], dict] = {}
        self._bytes: dict[tuple[str, str, int], bytes] = {}
        self.log: list[tuple[str, str, int]] = []  # ("head" | "read", artifact_id, version)
        self._lock = threading.Lock()
        self._prompt_versions = itertools.count(1)

    def put(
        self,
        artifact_id: str,
        version: int = 1,
        text: str | None = None,
        *,
        data: bytes | None = None,
        world_id: str = WORLD,
        run_id: str = RUN,
        media_type: str = "text/markdown",
        screening: str = "clean",
        origin: dict | None = None,
        idempotency_key: str | None = None,
        label: str | None = None,
    ) -> dict:
        payload = data if data is not None else (text or "x").encode("utf-8")
        ref: dict[str, Any] = {"artifact_id": artifact_id, "version": version}
        if label:
            ref["label"] = label
        origin = origin or {"kind": "upload", "unit": None, "agent": None}
        record = {
            "v": "1.0",
            "artifact": ref,
            "org_id": ORG,
            "world_id": world_id,
            "run_id": run_id,
            "owner": OWNER,
            "media_type": media_type,
            "size_bytes": max(1, len(payload)),
            "content_sha256": hashlib.sha256(payload).hexdigest(),
            "parents": [],
            "origin": origin,
            "sources": [],
            "screening": screening,
            "screened_at": None if screening == "unscreened" else T0,
            "redacted": False,
            "idempotency_key": idempotency_key,
            "created_at": T0,
        }
        with self._lock:
            self._records[(world_id, artifact_id, version)] = record
            self._bytes[(world_id, artifact_id, version)] = payload
        return {"artifact_id": artifact_id, "version": version}

    def put_prompt(self, prepared: Any, *, unit_id: str = UNIT, agent_id: str = AGENT, attempt: int = ATTEMPT) -> dict:
        """Store the prepared prompt the way the handoff unit does (AR-05 index 0); returns the record."""
        version = next(self._prompt_versions)
        self.put(
            "art_build_prompt",
            version,
            data=prepared.prompt.encode("utf-8"),
            world_id=prepared.world_id,
            run_id=prepared.run_id,
            media_type="text/markdown",
            origin={"kind": "unit", "unit": unit_id, "agent": agent_id},
            idempotency_key=f"{prepared.run_id}:{unit_id}:{attempt}:0",
            label="Build prompt",
        )
        return copy.deepcopy(self._records[(prepared.world_id, "art_build_prompt", version)])

    def replace_bytes(self, world_id: str, ref: dict, data: bytes) -> None:
        """Different bytes under the same ref (what a broken store, or an attacker, could do)."""
        with self._lock:
            self._bytes[(world_id, ref["artifact_id"], ref["version"])] = data

    def head(self, world_id: str, ref: Any) -> dict | None:
        key = (world_id, ref["artifact_id"], ref["version"])
        self.log.append(("head", key[1], key[2]))
        record = self._records.get(key)
        return copy.deepcopy(record) if record is not None else None

    def read(self, world_id: str, ref: Any) -> bytes:
        key = (world_id, ref["artifact_id"], ref["version"])
        self.log.append(("read", key[1], key[2]))
        return self._bytes[key]

    def touched(self, artifact_id: str) -> list[tuple[str, str, int]]:
        return [entry for entry in self.log if entry[1] == artifact_id]


def variant(stored: dict, **changes: Any) -> dict:
    """The store's record with some fields changed (a dotted key reaches into `origin`)."""
    out = copy.deepcopy(stored)
    for key, value in changes.items():
        if key.startswith("origin_"):
            out["origin"][key.removeprefix("origin_")] = value
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Wiring: the whole path, in memory


@dataclass
class Env:
    partner: Any
    registry: Any
    declaration: dict
    grants: Any
    artifacts: FakeTextArtifacts
    handoffs: Any
    links: Any
    adapter: Any
    outbox: Any
    emitted: list
    clock: ManualClock
    redact: Any
    safety: FakeSafety
    partners: dict = field(default_factory=dict)

    def with_partner(self, partner_config: Any) -> Env:
        """A second adapter and outbox over the same stores, with other limits (a limit lowered later)."""
        return _wire(
            partner_config,
            self.registry,
            self.grants,
            self.artifacts,
            self.handoffs,
            self.links,
            self.redact,
            self.safety,
            self.partners,
        )

    def transfers(self) -> list[dict]:
        return [p for p in self.emitted if p["type"] == "data.transfer"]


def _wire(partner_config, reg, grants, artifacts, handoffs, links, redact, safety, partners) -> Env:
    from tilo_connectors.outbox import Outbox
    from tilo_connectors.store import InMemoryOutboxStore

    decl = copy.deepcopy(dict(reg.get("lovable")))
    adapter = lv().LovableLinkAdapter(
        declaration=decl, partner=partner_config, handoffs=handoffs, grants=grants, artifacts=artifacts, links=links
    )
    emitted: list[dict] = []
    clock = ManualClock(T0)
    outbox = Outbox(InMemoryOutboxStore(), {"lovable": adapter}, emit=emitted.append, clock=clock)
    return Env(
        partner_config,
        reg,
        decl,
        grants,
        artifacts,
        handoffs,
        links,
        adapter,
        outbox,
        emitted,
        clock,
        redact,
        safety,
        partners,
    )


def make_env(
    tmp_path: pathlib.Path | None = None,
    *,
    secrets: tuple[str, ...] = (),
    flag_if: tuple[str, ...] = (),
    safety_raises: bool = False,
    links: Any = None,
    **limits: Any,
) -> Env:
    reg = registry()
    partners = load_partner(write_partners(tmp_path, **limits)) if limits else load_partner()
    partner_config = partners["lovable"]
    redact = make_redact(*secrets)
    safety = FakeSafety(flag_if, raises=safety_raises)
    return _wire(
        partner_config,
        reg,
        g().GrantStore(partners),
        FakeTextArtifacts(),
        h().HandoffStore(),
        links if links is not None else lv().InMemoryLinkStore(),
        redact,
        safety,
        partners,
    )


# ---------------------------------------------------------------------------
# The ordered flow (API doc "Ordered flow"), steps 1 to 7


def grant_items(*specs: tuple[str, int, str]) -> list:
    return [g().GrantItem(kind="artifact", ref=ref, version=ver, label=label) for ref, ver, label in specs]


def create_grant(env: Env, items: list, *, run_id: str = RUN, world_id: str = WORLD, connector: str = "lovable"):
    return env.grants.create(
        world_id=world_id, run_id=run_id, connector=connector, items=items, by=OWNER, world_owner=OWNER, at=T0
    )


def excerpts_for(env: Env, grant: Any, requests: list, *, redact: Any = None, safety: Any = None):
    return g().granted_excerpts(
        grants=env.grants,
        artifacts=env.artifacts,
        grant_id=grant.id,
        world_id=WORLD,
        run_id=RUN,
        connector="lovable",
        requests=requests,
        partner=env.partner,
        redact=redact or env.redact,
        safety=safety or env.safety,
    )


def prepare(env: Env, accepted: Any, *, framing: Any = GOOD_FRAMING, excerpts: Any = (), grant_id: Any = None, **over):
    kwargs: dict[str, Any] = {
        "accepted": accepted,
        "framing": framing,
        "excerpts": excerpts,
        "grant_id": grant_id,
        "grants": env.grants,
        "declined": declined(),
        "partner": env.partner,
        "declaration": env.declaration,
        "redact": env.redact,
        "safety": env.safety,
    }
    kwargs.update(over)
    return h().prepare_handoff(**kwargs)


@dataclass
class Flow:
    env: Env
    accepted: Any
    grant: Any
    excerpts: tuple
    prepared: Any
    stored: dict
    record: Any
    gate: dict
    case: dict


_ids = itertools.count(9300)


def next_outbox_id() -> str:
    return f"01JB5VQ000000000000000{next(_ids):04d}"


def build_case(
    record: Any, gate: dict, *, option: str = "approve", channel: str = "web", approver: str = OWNER
) -> dict:
    """A gate-authorised outbox case for the record: T3, external_sharing, no recipients, no destination."""
    outbox_id = next_outbox_id()
    case = gate_case(
        outbox_id=outbox_id,
        idempotency_key=f"{record.run_id}:{record.unit_id}:build_handoff:{outbox_id[-4:]}",
        connector=gate["connector"],
        action_type=gate["action_type"],
        recipients=(),
        destination=None,
        item=copy.deepcopy(gate["item"]),
        risk_tier=gate["risk_tier"],
        approver=approver,
        world_id=record.world_id,
        run_id=record.run_id,
    )
    case["entry"]["modifiers"] = list(gate["modifiers"])
    case["authorised_by"]["data"]["option"] = option
    case["authorised_by"]["data"]["channel"] = channel
    return case


def run_flow(
    env: Env,
    *,
    framing: Any = GOOD_FRAMING,
    grant_specs: tuple[tuple[str, int, str], ...] = (),
    texts: dict[tuple[str, int], str] | None = None,
    requests: list | None = None,
    accepted: Any = None,
) -> Flow:
    """Steps 1 to 7: accept, (grant, excerpt), prepare, store the prompt, record, gate. Nothing is enqueued."""
    accepted = accepted or accept()
    grant = None
    excerpts: tuple = ()
    if grant_specs:
        for (ref, ver), text in (texts or {}).items():
            env.artifacts.put(ref, ver, text)
        grant = create_grant(env, grant_items(*grant_specs))
        reqs = requests or [g().ExcerptRequest(ref=r, version=v, text=None) for r, v, _ in grant_specs]
        excerpts = excerpts_for(env, grant, reqs)
    prepared = prepare(env, accepted, framing=framing, excerpts=excerpts, grant_id=grant.id if grant else None)
    stored = env.artifacts.put_prompt(prepared)
    record = env.handoffs.record(prepared, stored, unit_id=UNIT, agent_id=AGENT, attempt=ATTEMPT)
    gate = h().handoff_gate(record, env.declaration)
    return Flow(env, accepted, grant, excerpts, prepared, stored, record, gate, build_case(record, gate))


def enqueue(env: Env, case: dict, *, option: str | None = None, authorised_by: Any = "keep") -> dict:
    from _connectors_lib import evidence_from_case

    evidence = evidence_from_case(copy.deepcopy(case))
    if option is not None:
        evidence["authorised_by"]["data"]["option"] = option
    if authorised_by != "keep":
        evidence["authorised_by"] = authorised_by
    return env.outbox.enqueue(copy.deepcopy(case["entry"]), evidence)


def settle(env: Env, case: dict) -> list[str]:
    """Enqueue (a refusal at enqueue is fine) and dispatch; the states the outbox ended with."""
    from tilo_connectors import OutboxRefused

    try:
        enqueue(env, case)
    except OutboxRefused:
        return ["refused"]
    return [e["state"] for e in env.outbox.dispatch_due()]


def link_url(env: Env) -> str:
    (link,) = env.links.links
    return json.loads(link.content.decode("ascii"))["url"]


def lowered(tmp_path: pathlib.Path, **limits: Any):
    return partner(tmp_path, **limits)


def everything_emitted(env: Env) -> str:
    return json.dumps(env.emitted, sort_keys=True, default=str)
