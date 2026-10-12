"""Doubles and wiring for the FR-CON-19 tests (Canva decks and documents). Pinned API: API_FR_CON_19.md.

No production code. `FakeCanva` is the fake Canva API (no network, no real Canva); `FakeTokens` is the token
seam. Fake secrets are assembled at runtime (root CLAUDE.md hard rule).
"""

from __future__ import annotations

import copy
import importlib
import itertools
import json
import pathlib
from dataclasses import dataclass
from typing import Any

from _connectors_lib import OWNER, RUN, WORLD, ManualClock
from _handoff_lib import AGENT, T0, UNIT, FakeSafety, FakeTextArtifacts, make_redact
from conftest import gate_case
from tilo_connectors import Outbox
from tilo_connectors.errors import AdapterError
from tilo_connectors.grants import GrantItem, GrantStore
from tilo_connectors.registry import load_registry
from tilo_connectors.store import InMemoryOutboxStore
from tilo_connectors.tokens import InsufficientScope, NotConnected
from tilo_policy import load_risk_table

CONFIG = pathlib.Path(__file__).resolve().parents[3] / "config"
PNG = b"\x89PNG\r\n\x1a\n" + b"logo-bytes"
PDF = b"%PDF-1.7 fake export"
PPTX = b"PK\x03\x04 fake deck"
EMAIL = "partner@vendor.example"
_ids = itertools.count(7100)


def cv():
    return importlib.import_module("tilo_connectors.canva")


def cva():
    return importlib.import_module("tilo_connectors.adapters.canva")


class CanvaDown(AdapterError):
    pass


class FakeCanva:
    """The Canva API double: records every call, answers from what the test sets."""

    def __init__(self, *, capabilities=("autofill", "brand_template"), caps_status: int | None = None) -> None:
        self.capabilities_ = frozenset(capabilities)
        self.caps_status = caps_status  # an HTTP status the capabilities call answers with
        self.autofill_status: int | None = None
        self.export_fails = 0
        self.export_bytes: bytes | None = None  # what export answers, instead of a real PDF or PPTX
        self.caps_failures = 0  # the next N capabilities calls answer 503
        self.create_raises: Exception | None = None  # raised by create_design (an ambiguous failure)
        self.share_raises: Exception | None = None
        self.calls: list[tuple[str, Any]] = []
        self.on_upload = None  # a hook run after each upload (a revoke mid-task)
        self.designs: dict[str, dict] = {}

    def of(self, name: str) -> list[Any]:
        return [c[1] for c in self.calls if c[0] == name]

    def capabilities(self, token: str) -> frozenset[str]:
        self.calls.append(("capabilities", token))
        if self.caps_failures:
            self.caps_failures -= 1
            raise cv().CanvaApiError(503)
        if self.caps_status:
            raise cv().CanvaApiError(self.caps_status)
        return self.capabilities_

    def upload_asset(self, token: str, *, name: str, media_type: str, data: bytes) -> str:
        self.calls.append(("upload", {"name": name, "media_type": media_type, "data": data}))
        asset_id = f"AS{len(self.of('upload'))}"
        if self.on_upload:
            self.on_upload()
        return asset_id

    def create_design(self, token: str, *, design_kind: str, title: str, pages: list, asset_ids: list) -> dict:
        self.calls.append(("create", {"design_kind": design_kind, "title": title, "pages": pages, "assets": asset_ids}))
        if self.create_raises is not None:
            raise self.create_raises
        return self._design("plain", title, pages, asset_ids)

    def autofill(self, token: str, *, brand_template_id: str, title: str, pages: list, asset_ids: list) -> dict:
        self.calls.append(("autofill", {"template": brand_template_id, "title": title, "pages": pages}))
        if self.autofill_status:
            raise cv().CanvaApiError(self.autofill_status)
        return self._design("autofill", title, pages, asset_ids)

    def _design(self, route: str, title: str, pages: list, asset_ids: list) -> dict:
        design_id = f"DA{len(self.designs) + 1}"
        self.designs[design_id] = {"route": route, "title": title, "pages": pages, "assets": asset_ids}
        return {"id": design_id, "url": f"https://canva.example/design/{design_id}"}

    def export(self, token: str, design_id: str, fmt: str) -> bytes:
        self.calls.append(("export", {"design_id": design_id, "format": fmt}))
        if self.export_fails:
            self.export_fails -= 1
            raise CanvaDown("export failed")
        if self.export_bytes is not None:
            return self.export_bytes
        return PDF if fmt == "pdf" else PPTX

    def share(self, token: str, design_id: str, emails: list) -> None:
        self.calls.append(("share", {"design_id": design_id, "emails": list(emails)}))
        if self.share_raises is not None:
            raise self.share_raises


class FakeTokens:
    """The token seam (TokenBroker.access_token_for_adapter's shape); the token is assembled at runtime."""

    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected
        self.missing: set[str] = set()  # scopes the person did not grant
        self.asked: list[dict] = []

    def access_token_for_adapter(self, user_id: str, connector: str, *, required_scopes, **kw: Any) -> str:
        self.asked.append({"user": user_id, "connector": connector, "scopes": list(required_scopes), **kw})
        if not self.connected:
            raise NotConnected("no connection for this user and connector")
        if gone := [s for s in required_scopes if s in self.missing]:
            raise InsufficientScope(gone)
        return "tok" + "en-" + user_id


def declaration() -> dict:
    return copy.deepcopy(dict(load_registry(CONFIG / "canva.yaml").get("canva")))


@dataclass
class Env:
    api: FakeCanva
    tokens: FakeTokens
    artifacts: FakeTextArtifacts
    grants: GrantStore
    exports: Any
    adapter: Any
    outbox: Outbox
    emitted: list
    redact: Any
    safety: FakeSafety
    table: Any

    def transfers(self) -> list[dict]:
        return [p for p in self.emitted if p["type"] == "data.transfer"]


def make_env(*, enabled: bool = True, secrets: tuple[str, ...] = (), flag_if: tuple[str, ...] = (), **api: Any) -> Env:
    api_double, tokens = FakeCanva(**api), FakeTokens()
    artifacts, exports = FakeTextArtifacts(), cva().InMemoryExportStore()
    grants = GrantStore({"canva": cv().canva_partner()})
    table = load_risk_table()
    redact, safety = make_redact(*secrets), FakeSafety(flag_if)
    adapter = cva().CanvaAdapter(
        declaration=declaration(),
        api=api_double,
        tokens=tokens,
        artifacts=artifacts,
        exports=exports,
        grants=grants,
        owner_of=lambda world_id: OWNER,
        redact=redact,
        safety=safety,
        risk_table=table,
        enabled=enabled,
    )
    emitted: list[dict] = []
    outbox = Outbox(InMemoryOutboxStore(), {"canva": adapter}, emit=emitted.append, clock=ManualClock(T0))
    return Env(
        api_double,
        tokens,
        artifacts,
        grants,
        exports,
        adapter,
        outbox,
        emitted,
        redact,
        safety,
        table,
    )


APPROVAL = {"by": "person", "ref": OWNER, "at": T0}


def seed(env: Env, *, texts=("Q3 plan: ship the Canva route", "Budget: INR 40,000"), assets=(("art_logo", 1),)):
    """Approved content and granted assets in the store; returns (content refs, asset refs, grant)."""
    content = []
    for i, text in enumerate(texts, start=1):
        content.append(env.artifacts.put(f"art_text{i}", 1, text, label=f"Section {i}"))
    refs = []
    for ref, version in assets:
        refs.append(env.artifacts.put(ref, version, data=PNG, media_type="image/png", label="Company logo"))
    grant = None
    if refs:
        grant = env.grants.create(
            world_id=WORLD,
            run_id=RUN,
            connector="canva",
            items=[GrantItem("artifact", r["artifact_id"], r["version"], "Company logo") for r in refs],
            by=OWNER,
            world_owner=OWNER,
            at=T0,
        )
    return content, refs, grant


def prepare(env: Env, content, refs=(), grant=None, **over: Any):
    kwargs: dict[str, Any] = {
        "world_id": WORLD,
        "run_id": RUN,
        "world_owner": OWNER,
        "approval": APPROVAL,
        "design_kind": "presentation",
        "content": content,
        "assets": refs,
        "grant_id": grant.id if grant else None,
        "grants": env.grants,
        "artifacts": env.artifacts,
        "redact": env.redact,
        "safety": env.safety,
    }
    kwargs.update(over)
    return cv().prepare_design(**kwargs)


def store_document(env: Env, prepared: Any) -> dict:
    """The design request as the unit stores it; returns its artifact ref."""
    return env.artifacts.put(
        "art_canva_request",
        1,
        data=prepared.document_bytes,
        media_type="application/json",
        label="Canva request",
        origin={"kind": "unit", "unit": UNIT, "agent": AGENT},
    )


def case_for(entry_fields: dict, *, approver: str = OWNER) -> dict:
    """A gate-authorised outbox case carrying the gate's fields (what the card builder copies)."""
    outbox_id = f"01JB5VQ000000000000000{next(_ids):04d}"
    case = gate_case(
        outbox_id=outbox_id,
        idempotency_key=f"{RUN}:{UNIT}:{entry_fields['action_type']}:{outbox_id[-4:]}",
        connector="canva",
        action_type=entry_fields["action_type"],
        recipients=tuple(entry_fields["recipients"]),
        destination=None,
        item=copy.deepcopy(entry_fields["item"]),
        risk_tier=entry_fields["risk_tier"],
        approver=approver,
    )
    case["entry"]["modifiers"] = list(entry_fields["modifiers"])
    case["entry"]["attachments"] = copy.deepcopy(entry_fields["attachments"])
    return case


def enqueue(env: Env, case: dict, *, option: str | None = None, drop_approval: bool = False) -> dict:
    from _connectors_lib import evidence_from_case

    evidence = evidence_from_case(copy.deepcopy(case))
    if option is not None:
        evidence["authorised_by"]["data"]["option"] = option
    if drop_approval:
        evidence["authorised_by"] = None
    return env.outbox.enqueue(copy.deepcopy(case["entry"]), evidence)


def design_case(env: Env, content, refs=(), grant=None, **over: Any) -> tuple[dict, Any]:
    prepared = prepare(env, content, refs, grant, **over)
    gate = cv().design_gate(prepared, store_document(env, prepared), table=env.table)
    return case_for(gate), prepared


def run_design(env: Env, content, refs=(), grant=None, **over: Any) -> tuple[list[str], Any]:
    case, prepared = design_case(env, content, refs, grant, **over)
    enqueue(env, case)
    return [e["state"] for e in env.outbox.dispatch_due()], prepared


def valid_document(env: Env, content, refs=(), grant=None, **over: Any) -> dict:
    """A copy of what prepare_design writes: the base a probe edits by hand."""
    return copy.deepcopy(prepare(env, content, refs, grant, **over).document)


def forged_case(env: Env, document: Any, *, attachments=None, risk_tier="T3", modifiers=None) -> dict:
    """An outbox case whose stored request is a hand-written document no prepare_design made."""
    raw = document if isinstance(document, bytes) else json.dumps(document, sort_keys=True).encode()
    item = env.artifacts.put(
        f"art_forged_{next(_ids)}",
        1,
        data=raw,
        media_type="application/json",
        origin={"kind": "unit", "unit": UNIT, "agent": AGENT},
    )
    assets = document.get("assets", []) if isinstance(document, dict) else []
    shown = (
        attachments
        if attachments is not None
        else [{"artifact_id": a["artifact_id"], "version": a["version"]} for a in assets if isinstance(a, dict)]
    )
    mods = modifiers if modifiers is not None else (["attachments"] if shown else [])
    fields = {
        "action_type": "create_design",
        "risk_tier": risk_tier,
        "modifiers": mods,
        "recipients": [],
        "attachments": shown,
        "item": item,
    }
    return case_for(fields)


def dispatch(env: Env, case: dict) -> list[str]:
    enqueue(env, case)
    return [e["state"] for e in env.outbox.dispatch_due()]
