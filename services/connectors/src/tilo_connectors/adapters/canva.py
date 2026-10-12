"""CanvaAdapter: Canva decks and documents from the outbox only (FR-CON-19, PRD supplement 2026-10-05 s6).

Two side effects, both T3 and both only with the grant `Outbox.dispatch_due()` minted (SEC-03): `create_design`
makes a presentation or document in the person's own Canva from the approved text versions and granted assets the
stored request names, uses brand-template autofill when the plan and the granted scopes allow and plain creation
otherwise, then exports PDF or PPTX and stores it as an artifact (unscreened: third-party bytes) with provenance;
`share_design` shares a design Tilo exported with outside recipients. The stored request is never trusted beyond
its hash: `canva.check_document`, the same function `prepare_design` runs, validates it again here (labels and
texts through the redactor and the safety screen, media types and magic bytes, the approver is the owner), and
every malformed shape ends the entry as a final refusal. Every call goes through the injected `CanvaApi`; the token
comes from the broker seam, never typed or stored here. The tier is recomputed from the risk table: a lower one is
refused. The at-most-once marker is set immediately before the one call that can act. Pinned API:
tests/API_FR_CON_19.md.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Protocol

import tilo_policy

from ..canva import (
    CANVA_ID,
    EXPORT_TYPES,
    NEEDS_APP,
    CanvaApi,
    CanvaApiError,
    check_document,
    declared_scopes,
)
from ..errors import HandoffRefused, MissingGrant, PossiblySent, SideEffectRefused
from ..outbox import Grant
from ..tokens import InsufficientScope
from ._google import side_effect_marker

if TYPE_CHECKING:
    from ..grants import GrantStore, TextArtifacts
    from ..handoff import Screen

_NOT_ON_PLAN = frozenset({402, 403, 404})  # Canva says the plan or the app does not offer it: fall back, no error
_MAGIC = {"pdf": b"%PDF", "pptx": b"PK"}
_MAX_EXPORT_BYTES = 50 * 1024 * 1024
_NEW: Any = object()  # no progress is recorded for this send yet


class TokenSource(Protocol):  # TokenBroker.access_token_for_adapter's shape; raises NotConnected, InsufficientScope
    def access_token_for_adapter(
        self, user_id: str, connector: str, *, required_scopes: Any, not_before: str | None = None
    ) -> str: ...


@dataclass(frozen=True)
class ExportArtifact:
    world_id: str
    run_id: str
    media_type: str
    content: bytes
    provenance: dict[str, Any]
    idempotency_key: str
    screening: str = "unscreened"  # bytes from a third party enter the store unscreened, like any download
    ref: dict[str, Any] | None = None


class ExportStore(Protocol):  # production: the artifact store bound to the world's scope
    def put(self, export: ExportArtifact) -> dict[str, Any]: ...  # the same idempotency_key returns the same ref

    def get(self, world_id: str, ref: Mapping[str, Any]) -> ExportArtifact | None: ...


@dataclass
class InMemoryExportStore:
    exports: list[ExportArtifact] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def put(self, export: ExportArtifact) -> dict[str, Any]:
        with self._lock:
            for kept in self.exports:
                if kept.idempotency_key == export.idempotency_key:
                    return dict(kept.ref or {})
            ref = {"artifact_id": f"art_canva_export_{len(self.exports) + 1}", "version": 1}
            self.exports.append(replace(export, ref=ref))
            return dict(ref)

    def get(self, world_id: str, ref: Mapping[str, Any]) -> ExportArtifact | None:
        with self._lock:
            ours = [e for e in self.exports if e.world_id == world_id and e.ref == dict(ref)]
            return ours[0] if ours else None


class CanvaAdapter:
    def __init__(
        self,
        *,
        declaration: Mapping[str, Any],
        api: CanvaApi,
        tokens: TokenSource,
        artifacts: TextArtifacts,
        exports: ExportStore,
        grants: GrantStore,
        owner_of: Callable[[str], str],
        redact: Callable[[str], str],
        safety: Screen,
        risk_table: tilo_policy.RiskTable | None = None,
        enabled: bool = False,
    ) -> None:
        self._decl = dict(declaration)
        self._api, self._tokens, self._artifacts, self._exports = api, tokens, artifacts, exports
        self._grants, self._owner_of, self._redact, self._safety = grants, owner_of, redact, safety
        self._table = risk_table if risk_table is not None else tilo_policy.load_risk_table()
        self._enabled = enabled  # off until the workspace owner's Canva app exists (canva_status)
        self._progress: dict[str, dict[str, Any] | None] = {}  # marker -> design/export so far; None = acting began
        self._lock = threading.Lock()  # BQ-CON19-1: in memory like the MCP ledger until the durable one exists

    @property
    def id(self) -> str:
        return CANVA_ID

    @property
    def declaration(self) -> dict[str, Any]:
        return dict(self._decl)

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Grant) -> dict[str, Any]:
        if not isinstance(grant, Grant) or grant.world_id != entry.get("world_id"):
            raise MissingGrant("grant not minted by Outbox.dispatch_due() for this exact send")
        grant.verify(entry["idempotency_key"])
        if not self._enabled:
            raise SideEffectRefused(NEEDS_APP)
        action = entry.get("action_type")
        if entry.get("connector") != CANVA_ID or action not in ("create_design", "share_design"):
            raise SideEffectRefused("the entry is not a Canva design action")
        if entry.get("destination") is not None or not isinstance(entry.get("item"), Mapping):
            raise SideEffectRefused("a Canva action has an item and no destination")
        modifiers = entry.get("modifiers") or []
        if entry.get("risk_tier") != self._table.tier_of(action, modifiers):  # never the caller's own tier
            raise SideEffectRefused("the entry's tier is not the risk table's")
        try:
            return self._create(entry) if action == "create_design" else self._share(entry)
        except HandoffRefused as exc:  # a revoked grant or content that changed: final, nothing more is sent
            raise SideEffectRefused(str(exc)) from None
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            raise SideEffectRefused("the entry or its stored request is malformed") from None

    # -- create_design -------------------------------------------------------------------------------------

    def _create(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        world_id = entry["world_id"]
        request, origin = self._request(entry)
        grant_items = None
        if request.get("assets"):
            grant_items = {
                (i.ref, i.version) for i in self._require_grant(entry, request).items if i.kind == "artifact"
            }
        pages, files = check_document(  # the same rules as prepare_design, over the stored request
            request,
            world_id=world_id,
            owner=self._owner_of(world_id),
            grant_items=grant_items,
            artifacts=self._artifacts,
            redact=self._redact,
            safety=self._safety,
            pinned=True,
        )
        bound = [(a["artifact_id"], a["version"]) for a in entry["attachments"]]
        owned = [(f.key["artifact_id"], f.key["version"]) for f in files]
        if entry["recipients"] or bound != owned or ("attachments" in entry["modifiers"]) != bool(owned):
            raise SideEffectRefused("the entry's attachments are not the request's granted assets")
        marker = side_effect_marker(entry)
        with self._lock:
            known = self._progress.get(marker, _NEW)
        if known is None:
            raise PossiblySent("an earlier attempt may have made the design; a person checks Canva")
        write = self._token(entry, "write")  # a wait for the person, or a failed read, sets no marker
        template = request["brand_template_id"]
        autofill_token = self._autofill_token(entry, write) if template and known is _NEW else None
        if known is _NEW:
            title = (pages[0].heading or "Tilo design")[:100]
            page_data = [{"heading": p.heading, "text": p.text} for p in pages]
            uploaded = []
            for f in files:
                self._require_grant(entry, request)  # revoking mid-task stops further uploads (FR-CON-20)
                uploaded.append(
                    self._api.upload_asset(write, name=f.key["artifact_id"], media_type=f.media_type, data=f.data)
                )
            with self._lock:  # immediately before the one call that makes the design
                self._progress[marker] = None
            try:
                design, route = self._make(request, title, page_data, uploaded, write, autofill_token)
            except CanvaApiError as exc:
                if (exc.status or 0) < 500:  # Canva refused or asked to wait: nothing was made
                    with self._lock:
                        self._progress.pop(marker, None)
                raise
            known = {"design_id": design["id"], "url": design.get("url"), "route": route, "export": None}
            with self._lock:
                self._progress[marker] = known
        if known["export"] is None:
            export = self._export(entry, request, origin, write, known)
            with self._lock:
                known["export"] = export
        return {"design_id": known["design_id"], "export": known["export"], "route": known["route"]}

    def _request(self, entry: Mapping[str, Any]) -> tuple[dict[str, Any], Mapping[str, Any]]:
        """The stored request document, parsed; its shape is checked by `check_document`, not trusted here."""
        world_id, ref = entry["world_id"], dict(entry["item"])
        head = self._artifacts.head(world_id, ref)
        if not isinstance(head, Mapping) or head.get("media_type") != "application/json":
            raise SideEffectRefused("the stored request is not a Canva design request")
        raw = self._artifacts.read(world_id, ref)
        if head.get("world_id") != world_id or hashlib.sha256(raw).hexdigest() != head.get("content_sha256"):
            raise SideEffectRefused("the stored request is not intact")
        try:
            request = json.loads(raw)
        except ValueError:
            raise SideEffectRefused("the stored request is not JSON") from None
        if not isinstance(request, dict):
            raise SideEffectRefused("the stored request is not a Canva design request")
        return request, head.get("origin") or {}  # origin is bookkeeping for provenance, not part of the document

    def _require_grant(self, entry: Mapping[str, Any], request: Mapping[str, Any]) -> Any:
        return self._grants.require_active(  # DG-03: active, for this world, run and Canva
            str(request.get("grant_id")), world_id=entry["world_id"], run_id=entry["run_id"], connector=CANVA_ID
        )

    def _autofill_token(self, entry: Mapping[str, Any], write: str) -> str | None:
        """A token that may use brand templates, only when the plan allows; None means plain creation (no error)."""
        try:
            token = self._token(entry, "write", "read")  # incremental: asked only for a brand template
        except InsufficientScope:  # the brand-template scopes were not granted: plain, with the write-only token
            return None
        try:
            return token if "autofill" in self._api.capabilities(token) else None
        except CanvaApiError as exc:
            if exc.status in _NOT_ON_PLAN:
                return None
            raise  # before the marker: a retry makes the design once

    def _make(
        self,
        request: Mapping[str, Any],
        title: str,
        pages: list[dict[str, str]],
        asset_ids: list[str],
        write: str,
        autofill_token: str | None,
    ) -> tuple[dict[str, Any], str]:
        if autofill_token is not None:
            try:
                design = self._api.autofill(
                    autofill_token,
                    brand_template_id=request["brand_template_id"],
                    title=title,
                    pages=pages,
                    asset_ids=asset_ids,
                )
                return design, "autofill"
            except CanvaApiError as exc:
                if exc.status not in _NOT_ON_PLAN:
                    raise
        design = self._api.create_design(
            write, design_kind=request["design_kind"], title=title, pages=pages, asset_ids=asset_ids
        )
        return design, "plain"

    def _export(
        self,
        entry: Mapping[str, Any],
        request: Mapping[str, Any],
        origin: Mapping[str, Any],
        token: str,
        made: Mapping[str, Any],
    ) -> Any:
        fmt = request["export_format"]
        data = self._api.export(token, made["design_id"], fmt)
        if not isinstance(data, bytes) or not 0 < len(data) <= _MAX_EXPORT_BYTES or not data.startswith(_MAGIC[fmt]):
            raise SideEffectRefused("Canva's export is not a usable file")
        parents = [{"artifact_id": i["artifact_id"], "version": i["version"]} for i in request["content"]]
        parents += [{"artifact_id": i["artifact_id"], "version": i["version"]} for i in request["assets"]]
        provenance = {
            "partner": CANVA_ID,
            "route": made["route"],
            "design_id": made["design_id"],
            "design_url": made["url"],
            "format": fmt,
            "outbox_id": entry["id"],
            "authz": dict(entry["authz"]),
            "parents": parents,
            "request": dict(entry["item"]),
            "grant_id": request["grant_id"],
            "origin": {"unit": origin.get("unit"), "agent": origin.get("agent")},
        }
        return self._exports.put(
            ExportArtifact(
                world_id=entry["world_id"],
                run_id=entry["run_id"],
                media_type=EXPORT_TYPES[fmt],
                content=data,
                provenance=provenance,
                idempotency_key=f"{entry['idempotency_key']}:export",
            )
        )

    # -- share_design --------------------------------------------------------------------------------------

    def _share(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        mods = set(entry.get("modifiers") or [])
        wanted = {"external_sharing", "new_recipients"}
        outside = bool(entry["recipients"]) and wanted <= mods and not entry["attachments"]
        export = self._exports.get(entry["world_id"], entry["item"]) if outside else None
        if not outside or export is None or export.provenance.get("partner") != CANVA_ID:
            raise SideEffectRefused("a share needs outside recipients and a design Tilo exported")
        marker = side_effect_marker(entry)
        with self._lock:
            earlier = self._progress.get(marker, _NEW)
        if earlier is None:
            raise PossiblySent("an earlier attempt may have shared the design; a person checks Canva")
        if earlier is _NEW:
            token = self._token(entry, "share")  # a wait for the person sets no marker
            with self._lock:  # immediately before the one call that shares
                self._progress[marker] = None
            try:
                self._api.share(token, export.provenance["design_id"], list(entry["recipients"]))
            except CanvaApiError as exc:
                if (exc.status or 0) < 500:  # Canva refused or asked to wait: nothing was shared
                    with self._lock:
                        self._progress.pop(marker, None)
                raise
            with self._lock:
                self._progress[marker] = {"shared": True}
        return {"design_id": export.provenance["design_id"], "shared_with": len(entry["recipients"])}

    def _token(self, entry: Mapping[str, Any], *capabilities: str) -> str:
        return self._tokens.access_token_for_adapter(
            self._owner_of(entry["world_id"]),
            CANVA_ID,
            required_scopes=declared_scopes(self._decl, *capabilities),
            not_before=entry["authz"]["at"],
        )
