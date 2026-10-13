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
import unicodedata
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import tilo_policy

from ._text import collapse, flagged, has_hidden, redacted_unchanged, safe_id
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


@dataclass(frozen=True)
class CheckedPage:
    key: dict[str, Any]  # {"artifact_id", "version"}
    sha: str
    heading: str  # the artifact's label, after the redactor, the safety screen and the hidden-character check
    text: str


@dataclass(frozen=True)
class CheckedAsset:
    key: dict[str, Any]
    sha: str
    media_type: str
    label: str
    data: bytes


_PNG, _JPEG = b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"
_DOC_KEYS = frozenset(
    {"v", "kind", "design_kind", "export_format", "brand_template_id", "approved", "content", "assets", "grant_id"}
)
_ITEM_KEYS = frozenset({"artifact_id", "version", "sha256"})
_MAX_LABEL = 120


def check_document(
    document: Any,
    *,
    world_id: str,
    owner: str,
    grant_items: Collection[tuple[str, int]] | None,
    artifacts: TextArtifacts,
    redact: Callable[[str], str],
    safety: Screen,
    pinned: bool,
) -> tuple[list[CheckedPage], list[CheckedAsset]]:
    """The one validation of a design request, run by `prepare_design` (pinned=False: shas and media types are
    filled in from what is read) and again by the adapter at dispatch (pinned=True: they must still match). Every
    malformed shape is a HandoffRefused, never another exception. CV-01 not approved by `owner`; CV-02 an item is
    not clean, intact content of this world; CV-03 the redactor, safety screen or hidden-character check (text and
    labels); CV-04 shape; DG-02 an asset not in `grant_items` (checked before any asset is read)."""
    try:
        return _check(document, world_id, owner, grant_items, artifacts, redact, safety, pinned)
    except HandoffRefused:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        raise HandoffRefused("CV-04", "the design request is malformed") from None


def _check(
    doc: Any,
    world_id: str,
    owner: str,
    grant_items: Collection[tuple[str, int]] | None,
    artifacts: TextArtifacts,
    redact: Callable[[str], str],
    safety: Screen,
    pinned: bool,
) -> tuple[list[CheckedPage], list[CheckedAsset]]:
    if not isinstance(doc, Mapping) or set(doc) != _DOC_KEYS or doc["v"] != "1.0" or doc["kind"] != "canva_design":
        raise HandoffRefused("CV-04", "not a Canva design request")
    kind, fmt, template = doc["design_kind"], doc["export_format"], doc["brand_template_id"]
    if not (isinstance(kind, str) and kind in DESIGN_KINDS and isinstance(fmt, str) and fmt in EXPORT_TYPES):
        raise HandoffRefused("CV-04", "the design kind or the export format is not offered")
    if template is not None and not (isinstance(template, str) and _TEMPLATE.fullmatch(template)):
        raise HandoffRefused("CV-04", "the brand template id is not an id")
    approved = doc["approved"]
    if not isinstance(approved, Mapping) or set(approved) != {"by", "ref", "at"} or approved["by"] != "person":
        raise HandoffRefused("CV-01", "the content was not approved by a person")
    if not isinstance(approved["ref"], str) or approved["ref"] != owner or not isinstance(approved["at"], str):
        raise HandoffRefused("CV-01", "the content was not approved by the world's owner")
    content, assets = doc["content"], doc["assets"]
    if not isinstance(content, list) or not 1 <= len(content) <= MAX_PAGES:
        raise HandoffRefused("CV-04", f"1 to {MAX_PAGES} content items")
    if not isinstance(assets, list) or len(assets) > MAX_ASSETS:
        raise HandoffRefused("CV-04", f"at most {MAX_ASSETS} assets")
    if bool(assets) != isinstance(doc["grant_id"], str):
        raise HandoffRefused("CV-04", "granted assets need a grant id, and a grant id needs assets")
    shapes = [(e, _ITEM_KEYS) for e in content] + [(e, _ITEM_KEYS | {"media_type"}) for e in assets]
    for entry, keys in shapes:
        if not isinstance(entry, Mapping) or set(entry) != keys:
            raise HandoffRefused("CV-04", "an item holds only its id, version, hash and (assets) media type")
        if not isinstance(entry["artifact_id"], str) or type(entry["version"]) is not int:
            raise HandoffRefused("CV-04", "an item needs an artifact id and an integer version")
    for entry in assets:  # DG-02, before any asset is read
        if grant_items is None or (entry["artifact_id"], entry["version"]) not in grant_items:
            raise HandoffRefused("DG-02", f"{safe_id(entry['artifact_id'])} is not an item of the grant")
    pages = [_page(world_id, e, artifacts, redact, safety, pinned) for e in content]
    files = [_asset(world_id, e, artifacts, redact, safety, pinned) for e in assets]
    return pages, files


def _head(artifacts: TextArtifacts, world_id: str, entry: Mapping[str, Any], types: frozenset[str]) -> Any:
    key = {"artifact_id": entry["artifact_id"], "version": entry["version"]}
    head = artifacts.head(world_id, key)
    if (
        not isinstance(head, Mapping)
        or head.get("world_id") != world_id
        or head.get("media_type") not in types
        or head.get("screening") != "clean"
    ):
        raise HandoffRefused("CV-02", f"{safe_id(key['artifact_id'])} is not a clean item of this world")
    return key, head


def _bytes(
    artifacts: TextArtifacts, world_id: str, key: Mapping[str, Any], head: Mapping[str, Any]
) -> tuple[bytes, str]:
    raw = artifacts.read(world_id, dict(key))
    sha = hashlib.sha256(raw).hexdigest() if isinstance(raw, bytes) else ""
    if sha != head.get("content_sha256"):
        raise HandoffRefused("CV-02", f"{safe_id(key['artifact_id'])} is not intact")
    return raw, sha


def _clean(text: str, key: Mapping[str, Any], redact: Any, safety: Any) -> None:
    if has_hidden(text) or not redacted_unchanged(redact, text) or flagged(safety, text):
        raise HandoffRefused("CV-03", f"{safe_id(key['artifact_id'])} did not pass the redactor and the safety screen")


def _label(head: Mapping[str, Any], key: Mapping[str, Any], redact: Any, safety: Any) -> str:
    """The artifact's label becomes a heading, the title and card text, so it is screened like the text."""
    label = (head.get("artifact") or {}).get("label")
    if label is None or label == "":
        return ""
    plain = isinstance(label, str) and label == collapse(label) and len(label) <= _MAX_LABEL
    if not plain or any(unicodedata.category(c) == "Cc" for c in label):
        raise HandoffRefused("CV-03", f"the label of {safe_id(key['artifact_id'])} is not plain short text")
    _clean(label, key, redact, safety)
    return str(label)


def _page(
    world_id: str, entry: Mapping[str, Any], artifacts: TextArtifacts, redact: Any, safety: Any, pinned: bool
) -> CheckedPage:
    key, head = _head(artifacts, world_id, entry, TEXT_TYPES)
    raw, sha = _bytes(artifacts, world_id, key, head)
    if pinned and sha != entry["sha256"]:
        raise HandoffRefused("CV-02", f"{safe_id(key['artifact_id'])} changed after it was approved")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    if not text or len(text) > MAX_PAGE_CHARS:
        raise HandoffRefused("CV-02", f"{safe_id(key['artifact_id'])} is not text within the page limit")
    _clean(text, key, redact, safety)
    return CheckedPage(key, sha, _label(head, key, redact, safety), text)


def _asset(
    world_id: str, entry: Mapping[str, Any], artifacts: TextArtifacts, redact: Any, safety: Any, pinned: bool
) -> CheckedAsset:
    key, head = _head(artifacts, world_id, entry, ASSET_TYPES)
    size = head.get("size_bytes")
    if type(size) is not int or not 0 < size <= MAX_ASSET_BYTES:
        raise HandoffRefused("CV-02", f"{safe_id(key['artifact_id'])} is not within the asset size limit")
    raw, sha = _bytes(artifacts, world_id, key, head)
    media = head["media_type"]
    if len(raw) > MAX_ASSET_BYTES or not raw.startswith(_PNG if media == "image/png" else _JPEG):
        raise HandoffRefused("CV-02", f"{safe_id(key['artifact_id'])} is not the image it is declared to be")
    if pinned and (sha != entry["sha256"] or media != entry["media_type"]):
        raise HandoffRefused("CV-02", f"{safe_id(key['artifact_id'])} changed after it was granted")
    return CheckedAsset(key, sha, media, _label(head, key, redact, safety), raw)


def _card(design_kind: str, fmt: str, pages: Sequence[CheckedPage], assets: Sequence[CheckedAsset]) -> str:
    """What the person is shown (gate.action.exact, at most 500 characters): the labels of what goes to Canva. When
    the full list does not fit it says how many more there are."""
    shown_pages = [p.heading or p.key["artifact_id"] for p in pages]
    shown_assets = [a.label or a.key["artifact_id"] for a in assets]

    def listed(items: list[str], n: int, noun: str) -> str:
        more = f" and {len(items) - n} more" if n < len(items) else ""
        plural = "s" if len(items) != 1 else ""
        return f"{len(items)} {noun}{plural}" + (f" ({'; '.join(items[:n])}{more})" if n else "")

    head = f"Sends this content to Canva, a third-party service, to make a {design_kind} in your own Canva: "
    tail = f". Then exports a {fmt.upper()} back into Tilo. Nothing is shared with anyone else."
    for n_pages in range(len(pages), -1, -1):
        for n_assets in range(len(assets), -1, -1):
            text = head + listed(shown_pages, n_pages, "page")
            if assets:
                text += " and " + listed(shown_assets, n_assets, "granted asset")
            if len(text + tail) <= 500:
                return text + tail
    return head + tail  # not reached: the counts alone always fit


class PreparedDesign:
    """The request document a person sees at the gate and the adapter re-checks at dispatch."""

    def __init__(
        self,
        world_id: str,
        run_id: str,
        document: dict[str, Any],
        pages: Sequence[CheckedPage],
        files: Sequence[CheckedAsset],
    ) -> None:
        self.world_id, self.run_id, self.document = world_id, run_id, document
        self.document_bytes = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        self.assets = [dict(a.key) for a in files]
        self.exact = _card(document["design_kind"], document["export_format"], pages, files)


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
    """The design request, or HandoffRefused (rules as in `check_document`; DG-03 a grant that is not active)."""
    granted: set[tuple[str, int]] | None = None
    if assets:  # DG-03 here; DG-02 inside check_document, before any asset is read
        grant = grants.require_active(str(grant_id), world_id=world_id, run_id=run_id, connector=CANVA_ID)
        granted = {(i.ref, i.version) for i in grant.items if i.kind == "artifact" and i.version is not None}
    document: dict[str, Any] = {
        "v": "1.0",
        "kind": "canva_design",
        "design_kind": design_kind,
        "export_format": export_format,
        "brand_template_id": brand_template_id,
        "approved": dict(approval) if isinstance(approval, Mapping) else approval,
        "content": [_entry(r) for r in content],
        "assets": [_entry(r, media_type=None) for r in assets],
        "grant_id": grant_id if assets else None,
    }
    pages, files = check_document(
        document,
        world_id=world_id,
        owner=world_owner,
        grant_items=granted,
        artifacts=artifacts,
        redact=redact,
        safety=safety,
        pinned=False,
    )
    for entry, page in zip(document["content"], pages, strict=True):
        entry["sha256"] = page.sha
    for entry, asset in zip(document["assets"], files, strict=True):
        entry["sha256"], entry["media_type"] = asset.sha, asset.media_type
    return PreparedDesign(world_id, run_id, document, pages, files)


def _entry(ref: Any, **extra: Any) -> dict[str, Any]:
    get = ref.get if isinstance(ref, Mapping) else (lambda _key: None)
    return {"artifact_id": get("artifact_id"), "version": get("version"), "sha256": None, **extra}


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
