"""tilo_connectors.canva — Canva decks and documents (FR-CON-19, PRD supplement 2026-10-05 s6, SD-03).

With the person's OAuth grant Tilo makes a presentation or document in the person's own Canva from approved content,
uploads only the company assets the person granted for the task, and exports a PDF or PPTX back as an artifact.
This module is the pure half: `prepare_design` builds the request document from approved, screened artifact versions
and granted assets only (no model, no network); `design_gate` and `share_gate` make the gate fields the card builder
and the outbox entry copy, with the tier taken from the risk table. The side effects run in
`adapters/canva.py`, from the outbox only (SEC-03). Pinned API: services/connectors/tests/API_FR_CON_19.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import tilo_policy

from ._text import flagged, has_hidden, redacted_unchanged, safe_id
from .errors import CanvaApiError as CanvaApiError
from .errors import HandoffRefused
from .handoff import BuildPartnerConfig
from .registry import load_registry

if TYPE_CHECKING:
    from .grants import GrantStore, TextArtifacts
    from .handoff import Screen

CANVA_ID = "canva"
NEEDS_APP = "Needs the workspace owner's Canva app"
ENV_CLIENT_ID, ENV_CLIENT_SECRET = "CANVA_OAUTH_CLIENT_ID", "CANVA_OAUTH_CLIENT_SECRET"  # names only, never values
DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "config" / "canva.yaml"
DESIGN_KINDS = ("presentation", "document")
PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
EXPORT_TYPES = {"pdf": "application/pdf", "pptx": PPTX_TYPE}
ASSET_TYPES = frozenset({"image/png", "image/jpeg"})
TEXT_TYPES = frozenset({"text/markdown", "text/plain"})
MAX_PAGES, MAX_ASSETS, MAX_PAGE_CHARS, MAX_ASSET_BYTES = 30, 6, 5000, 10 * 1024 * 1024
_TEMPLATE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,255}")


class CanvaApi(Protocol):
    """The Canva Connect calls the adapter makes; tests inject a fake, a live transport comes with the user's app."""

    def capabilities(self, token: str) -> frozenset[str]: ...  # e.g. {"autofill", "brand_template"}

    def upload_asset(self, token: str, *, name: str, media_type: str, data: bytes) -> str: ...

    def create_design(
        self, token: str, *, design_kind: str, title: str, pages: list[dict[str, str]], asset_ids: list[str]
    ) -> dict[str, Any]: ...  # {"id", "url"}

    def autofill(
        self, token: str, *, brand_template_id: str, title: str, pages: list[dict[str, str]], asset_ids: list[str]
    ) -> dict[str, Any]: ...

    def export(self, token: str, design_id: str, fmt: str) -> bytes: ...

    def share(self, token: str, design_id: str, emails: list[str]) -> None: ...


def canva_status(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Honest state of the connector: it is off until the workspace owner has registered a Canva app (HR-1)."""
    env = os.environ if environ is None else environ
    if env.get(ENV_CLIENT_ID) and env.get(ENV_CLIENT_SECRET):
        return {"connector": CANVA_ID, "state": "ready_to_connect", "message": "Ready: connect your Canva account"}
    return {"connector": CANVA_ID, "state": "needs_setup", "message": NEEDS_APP}


def load_canva_declaration(path: str | os.PathLike[str] = DEFAULT_CONFIG) -> dict[str, Any]:
    return load_registry(path).get(CANVA_ID)


def declared_scopes(declaration: Mapping[str, Any], *capabilities: str) -> list[str]:
    return [s for c in capabilities for s in declaration["scopes"].get(c, ())]


def canva_partner() -> BuildPartnerConfig:
    """Limits for the data grant store (FR-CON-20): Canva is a build partner with at most MAX_ASSETS items."""
    return BuildPartnerConfig(
        connector=CANVA_ID,
        action="create_design",
        route="design",
        max_prompt_chars=MAX_PAGE_CHARS,
        max_url_length=1,
        max_framing_chars=1,
        max_excerpt_chars=MAX_PAGE_CHARS,
        max_items=MAX_ASSETS,
        framing_words=frozenset(),
    )


class PreparedDesign:
    """The request document a person sees at the gate and the adapter re-checks at dispatch."""

    def __init__(self, world_id: str, run_id: str, document: dict[str, Any]) -> None:
        self.world_id, self.run_id, self.document = world_id, run_id, document
        self.document_bytes = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        self.assets = [{"artifact_id": a["artifact_id"], "version": a["version"]} for a in document["assets"]]
        n, m = len(document["content"]), len(self.assets)
        self.exact = (
            f"Makes a Canva {document['design_kind']} in your own Canva from {n} approved item{'s' * (n != 1)}"
            f" and {m} granted asset{'s' * (m != 1)}, then exports a {document['export_format'].upper()} back into"
            " Tilo. Nothing is shared outside your company."
        )


def prepare_design(
    *,
    world_id: str,
    run_id: str,
    world_owner: str,
    approval: Mapping[str, Any],
    design_kind: str,
    content: Sequence[Mapping[str, Any]],
    assets: Sequence[Mapping[str, Any]] = (),
    grant_id: str | None = None,
    grants: GrantStore,
    artifacts: TextArtifacts,
    redact: Callable[[str], str],
    safety: Screen,
    brand_template_id: str | None = None,
    export_format: str = "pdf",
) -> PreparedDesign:
    """The design request, or HandoffRefused. CV-01 not approved by the owner; CV-02 content not clean approved
    text; CV-03 redactor or safety screen; CV-04 shape; DG-02 and DG-03 as in grants.py (checked before any read)."""
    if design_kind not in DESIGN_KINDS or export_format not in EXPORT_TYPES:
        raise HandoffRefused("CV-04", "the design kind or the export format is not offered")
    if brand_template_id is not None and not _TEMPLATE.fullmatch(str(brand_template_id)):
        raise HandoffRefused("CV-04", "the brand template id is not an id")
    if not 1 <= len(content) <= MAX_PAGES or len(assets) > MAX_ASSETS:
        raise HandoffRefused("CV-04", f"1 to {MAX_PAGES} content items and at most {MAX_ASSETS} assets")
    owner_ok = isinstance(approval, Mapping) and set(approval) == {"by", "ref", "at"}
    if not owner_ok or approval["by"] != "person" or approval["ref"] != world_owner:
        raise HandoffRefused("CV-01", "the content was not approved by the world's owner")
    if assets:  # DG-03 then DG-02, before anything is read
        grant = grants.require_active(str(grant_id), world_id=world_id, run_id=run_id, connector=CANVA_ID)
        granted = {(i.ref, i.version) for i in grant.items if i.kind == "artifact"}
        for ref in assets:
            if (ref.get("artifact_id"), ref.get("version")) not in granted:
                raise HandoffRefused("DG-02", f"{safe_id(ref.get('artifact_id'))} is not an item of grant {grant.id}")
    pages = [_page(world_id, ref, artifacts, redact, safety) for ref in content]
    files = [_asset(world_id, ref, artifacts) for ref in assets]
    document = {
        "v": "1.0",
        "kind": "canva_design",
        "design_kind": design_kind,
        "export_format": export_format,
        "brand_template_id": brand_template_id,
        "approved": dict(approval),
        "content": pages,
        "assets": files,
        "grant_id": grant_id if assets else None,
    }
    return PreparedDesign(world_id, run_id, document)


def _head(artifacts: TextArtifacts, world_id: str, ref: Mapping[str, Any], rule: str, types: frozenset[str]) -> Any:
    key = {"artifact_id": ref.get("artifact_id"), "version": ref.get("version")}
    head = artifacts.head(world_id, key)
    if (
        not isinstance(head, Mapping)
        or head.get("world_id") != world_id
        or head.get("media_type") not in types
        or head.get("screening") != "clean"
        or type(key["version"]) is not int
    ):
        raise HandoffRefused(rule, f"{safe_id(key['artifact_id'])} is not a clean item of this world")
    return key, head


def _page(world_id: str, ref: Mapping[str, Any], artifacts: TextArtifacts, redact: Any, safety: Any) -> dict[str, Any]:
    key, head = _head(artifacts, world_id, ref, "CV-02", TEXT_TYPES)
    raw = artifacts.read(world_id, key)
    try:
        text = raw.decode("utf-8")
        intact = hashlib.sha256(raw).hexdigest() == head.get("content_sha256")
    except UnicodeDecodeError:
        text, intact = "", False
    if not intact or not text or len(text) > MAX_PAGE_CHARS:
        raise HandoffRefused("CV-02", f"{safe_id(key['artifact_id'])} is not intact text within the page limit")
    if has_hidden(text) or not redacted_unchanged(redact, text) or flagged(safety, text):
        raise HandoffRefused("CV-03", f"{safe_id(key['artifact_id'])} did not pass the redactor and the safety screen")
    return {**key, "sha256": head["content_sha256"]}


def _asset(world_id: str, ref: Mapping[str, Any], artifacts: TextArtifacts) -> dict[str, Any]:
    key, head = _head(artifacts, world_id, ref, "CV-02", ASSET_TYPES)
    if not 0 < int(head.get("size_bytes", 0)) <= MAX_ASSET_BYTES:
        raise HandoffRefused("CV-02", f"{safe_id(key['artifact_id'])} is over the asset size limit")
    return {**key, "sha256": head["content_sha256"], "media_type": head["media_type"]}


def design_gate(prepared: PreparedDesign, item: Mapping[str, Any], *, table: tilo_policy.RiskTable) -> dict[str, Any]:
    """What the card and the outbox entry copy for a design. Granted assets are attachments, which raise it to T3."""
    modifiers = ["attachments"] if prepared.assets else []
    return {
        "action_type": "create_design",
        "connector": CANVA_ID,
        "risk_tier": table.tier_of("create_design", modifiers),
        "irreversible": False,
        "modifiers": modifiers,
        "recipients": [],
        "attachments": list(prepared.assets),
        "item": {"artifact_id": item["artifact_id"], "version": item["version"]},
        "destination": None,
        "exact": prepared.exact,
        "undo_window_s": 0,
    }


def share_gate(export: Mapping[str, Any], recipients: Sequence[str], *, table: tilo_policy.RiskTable) -> dict[str, Any]:
    """Sharing a design outside the company: new recipients and external sharing, so T3 and a person decides."""
    if not 1 <= len(recipients) <= 50 or not all(isinstance(r, str) and _EMAIL.fullmatch(r) for r in recipients):
        raise HandoffRefused("CV-04", "a share names 1 to 50 email addresses")
    modifiers = ["external_sharing", "new_recipients"]
    exact = f"Shares the exported Canva design with people outside your company: {', '.join(recipients)}."
    if len(exact) > 500:  # never cut what the card shows
        raise HandoffRefused("CV-04", "the share card text would be over 500 characters")
    return {
        "action_type": "share_design",
        "connector": CANVA_ID,
        "risk_tier": table.tier_of("share_design", modifiers),
        "irreversible": True,
        "modifiers": modifiers,
        "recipients": list(recipients),
        "attachments": [],
        "item": {"artifact_id": export["artifact_id"], "version": export["version"]},
        "destination": None,
        "exact": exact,
        "undo_window_s": 0,
    }
