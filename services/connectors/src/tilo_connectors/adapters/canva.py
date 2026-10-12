"""CanvaAdapter: Canva decks and documents from the outbox only (FR-CON-19, PRD supplement 2026-10-05 s6).

Two side effects, both T3 and both only with the grant `Outbox.dispatch_due()` minted (SEC-03): `create_design`
makes a presentation or document in the person's own Canva from the approved text versions and granted assets the
stored request names (each re-checked against the hash the person approved, the grant re-checked before every
upload), uses brand-template autofill when the plan allows and plain creation otherwise, then exports PDF or PPTX
and stores it as an artifact with provenance; `share_design` shares a design Tilo exported with outside recipients.
Every call goes through the injected `CanvaApi`; the token comes from the broker seam, never typed or stored here.
The tier is recomputed from the risk table: a lower one is refused. Pinned API: tests/API_FR_CON_19.md.
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
    declared_scopes,
)
from ..errors import HandoffRefused, MissingGrant, PossiblySent, SideEffectRefused
from ..outbox import Grant
from ._google import side_effect_marker

if TYPE_CHECKING:
    from ..grants import GrantStore, TextArtifacts

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
        risk_table: tilo_policy.RiskTable | None = None,
        enabled: bool = False,
    ) -> None:
        self._decl = dict(declaration)
        self._api, self._tokens, self._artifacts, self._exports = api, tokens, artifacts, exports
        self._grants, self._owner_of = grants, owner_of
        self._table = risk_table if risk_table is not None else tilo_policy.load_risk_table()
        self._enabled = enabled  # off until the workspace owner's Canva app exists (canva_status)
        self._progress: dict[str, dict[str, Any] | None] = {}  # marker -> design/export so far; None = create began
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

    # -- create_design -------------------------------------------------------------------------------------

    def _create(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        world_id = entry["world_id"]
        request = self._request(entry)
        assets = request["assets"]
        shaped = not entry["recipients"] and ("attachments" in entry["modifiers"]) == bool(assets)
        if not shaped or [(a["artifact_id"], a["version"]) for a in entry["attachments"]] != [
            (a["artifact_id"], a["version"]) for a in assets
        ]:
            raise SideEffectRefused("the entry's attachments are not the request's granted assets")
        marker = side_effect_marker(entry)
        with self._lock:
            known = self._progress.get(marker, _NEW)
        if known is None:
            raise PossiblySent("an earlier attempt may have made the design; a person checks Canva")
        pages, files = self._pages(world_id, request), self._files(entry, request)  # all re-checked before any call
        token = self._token(entry, "write", *(("read",) if request["brand_template_id"] else ()))
        if known is _NEW:
            uploaded = []
            for name, media_type, data in files:
                self._require_grant(entry, request)  # revoking mid-task stops further uploads (FR-CON-20)
                uploaded.append(self._api.upload_asset(token, name=name, media_type=media_type, data=data))
            with self._lock:
                self._progress[marker] = None  # recorded before the call: a retry never makes a second design
            design, route = self._design(token, request, pages, uploaded)
            known = {"design_id": design["id"], "url": design.get("url"), "route": route, "export": None}
            with self._lock:
                self._progress[marker] = known
        if known["export"] is None:
            known["export"] = self._export(entry, request, token, known)
        return {"design_id": known["design_id"], "export": known["export"], "route": known["route"]}

    def _request(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        world_id, ref = entry["world_id"], dict(entry["item"])
        head = self._artifacts.head(world_id, ref)
        raw = self._artifacts.read(world_id, ref) if head is not None else b""
        try:
            request = json.loads(raw)
            assert head is not None
            ok = head.get("media_type") == "application/json" and head.get("world_id") == world_id
            ok = ok and hashlib.sha256(raw).hexdigest() == head.get("content_sha256")
            ok = ok and request["kind"] == "canva_design" and request["approved"]["by"] == "person"
        except (ValueError, KeyError, TypeError, AttributeError, AssertionError):
            ok = False
        if not ok or head is None:
            raise SideEffectRefused("the stored request is not an approved Canva design request")
        request["origin"] = head.get("origin")
        return dict(request)

    def _pages(self, world_id: str, request: Mapping[str, Any]) -> list[dict[str, str]]:
        pages = []
        for item in request["content"]:  # only the approved text versions, byte for byte as approved
            ref = {"artifact_id": item["artifact_id"], "version": item["version"]}
            head, raw = self._artifacts.head(world_id, ref), self._artifacts.read(world_id, ref)
            if not head or head.get("screening") != "clean" or hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise SideEffectRefused("approved content changed after it was approved")
            label = (head.get("artifact") or {}).get("label") or ""
            pages.append({"heading": str(label), "text": raw.decode("utf-8")})
        return pages

    def _require_grant(self, entry: Mapping[str, Any], request: Mapping[str, Any]) -> Any:
        return self._grants.require_active(  # DG-03: active, for this world, run and Canva
            str(request["grant_id"]), world_id=entry["world_id"], run_id=entry["run_id"], connector=CANVA_ID
        )

    def _files(self, entry: Mapping[str, Any], request: Mapping[str, Any]) -> list[tuple[str, str, bytes]]:
        files: list[tuple[str, str, bytes]] = []
        if not request["assets"]:
            return files
        granted = {(i.ref, i.version) for i in self._require_grant(entry, request).items}
        for item in request["assets"]:  # DG-02: only items of the grant, only the approved bytes
            if (item["artifact_id"], item["version"]) not in granted:
                raise SideEffectRefused("an asset is not an item of the grant")
            ref = {"artifact_id": item["artifact_id"], "version": item["version"]}
            raw = self._artifacts.read(entry["world_id"], ref)
            if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise SideEffectRefused("a granted asset changed after it was granted")
            files.append((item["artifact_id"], item["media_type"], raw))
        return files

    def _design(
        self, token: str, request: Mapping[str, Any], pages: list[dict[str, str]], asset_ids: list[str]
    ) -> tuple[dict[str, Any], str]:
        title = (pages[0]["heading"] or "Tilo design")[:100]
        template = request["brand_template_id"]
        if template and self._plan_allows_autofill(token):
            try:
                design = self._api.autofill(
                    token, brand_template_id=template, title=title, pages=pages, asset_ids=asset_ids
                )
                return design, "autofill"
            except CanvaApiError as exc:
                if exc.status not in _NOT_ON_PLAN:
                    raise
        design = self._api.create_design(
            token, design_kind=request["design_kind"], title=title, pages=pages, asset_ids=asset_ids
        )
        return design, "plain"

    def _plan_allows_autofill(self, token: str) -> bool:
        try:
            return "autofill" in self._api.capabilities(token)
        except CanvaApiError as exc:
            if exc.status in _NOT_ON_PLAN:
                return False
            raise

    def _export(self, entry: Mapping[str, Any], request: Mapping[str, Any], token: str, made: Mapping[str, Any]) -> Any:
        fmt = request["export_format"]
        data = self._api.export(token, made["design_id"], fmt)
        if not isinstance(data, bytes) or not 0 < len(data) <= _MAX_EXPORT_BYTES or not data.startswith(_MAGIC[fmt]):
            raise SideEffectRefused("Canva's export is not a usable file")
        origin = request.get("origin") or {}
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
        outside = (
            bool(entry["recipients"]) and {"external_sharing", "new_recipients"} <= mods and not entry["attachments"]
        )
        export = self._exports.get(entry["world_id"], entry["item"]) if outside else None
        if not outside or export is None or export.provenance.get("partner") != CANVA_ID:
            raise SideEffectRefused("a share needs outside recipients and a design Tilo exported")
        marker = side_effect_marker(entry)
        with self._lock:
            earlier = self._progress.get(marker, _NEW)
            if earlier is _NEW:
                self._progress[marker] = None
        if earlier is None:
            raise PossiblySent("an earlier attempt may have shared the design; a person checks Canva")
        if earlier is _NEW:
            token = self._token(entry, "share")
            self._api.share(token, export.provenance["design_id"], list(entry["recipients"]))
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
