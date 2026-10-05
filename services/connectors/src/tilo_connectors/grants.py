"""tilo_connectors.grants — granted company data for a build partner (FR-CON-20, DG-01..DG-05).

A grant is made by the world's owner for one task (world and run) and one partner, names 1 to `max_items` items, and
ends with the run or when the owner revokes it. On the link route nothing is uploaded: an item outside the grant is
never read and never included. What is read is clean text of this world, cut to a contiguous excerpt, passed through
the injected redactor and then the safety screen. No network, no model. Pinned API:
services/connectors/tests/API_FR_CON_16_17_20.md.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import secrets
import threading
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ._text import collapse, flagged, safe_id
from .errors import HandoffRefused

if TYPE_CHECKING:
    from .handoff import BuildPartnerConfig, Screen

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ARTIFACT = re.compile(r"art_[0-9A-Za-z_]{1,48}")  # common.schema.json artifact_id
_FOLDER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}")  # common.schema.json destination
_RECORD = re.compile(
    r"(?:work_item|calendar_entry|meeting|pinboard_item|mention|card|world|event):[A-Za-z0-9_]{1,64}"
)  # record_ref kind and id
_KINDS = {"artifact": _ARTIFACT, "folder": _FOLDER, "record": _RECORD}
_TEXT_TYPES = frozenset({"text/markdown", "text/csv", "application/json"})
_MAX_LABEL = 80


@dataclass(frozen=True)
class GrantItem:
    kind: str  # "artifact" | "folder" | "record"
    ref: str
    version: int | None  # artifact: the pinned version; folder and record: None
    label: str  # the excerpt heading


@dataclass(frozen=True)
class DataGrant:
    id: str
    world_id: str
    run_id: str
    connector: str
    items: tuple[GrantItem, ...]
    granted_by: str
    granted_at: str
    state: str  # "active" | "revoked" | "expired"
    ended_at: str | None
    ended_by: str | None  # the owner for revoked, None for expired


def _item_problem(item: Any) -> str | None:
    if not isinstance(item, GrantItem):
        return "an item is not a GrantItem"
    shape = _KINDS.get(item.kind) if isinstance(item.kind, str) else None
    if shape is None or not isinstance(item.ref, str) or not shape.fullmatch(item.ref):
        return "an item has a kind or ref of the wrong shape"
    if item.kind == "artifact":
        if type(item.version) is not int or item.version < 1:
            return "an artifact item needs a pinned version"
    elif item.version is not None:
        return "only an artifact item has a version"
    label = item.label
    if not isinstance(label, str) or not 1 <= len(collapse(label)) <= _MAX_LABEL:
        return "an item label must be 1 to 80 characters"
    if any(unicodedata.category(c) == "Cc" for c in label):
        return "an item label holds a control character"
    return None


class GrantStore:
    """In memory and lock-guarded; every grant is immutable, so reads hand out the stored object."""

    def __init__(self, partners: Mapping[str, BuildPartnerConfig]) -> None:
        self._partners = dict(partners)
        self._grants: dict[str, DataGrant] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        world_id: str,
        run_id: str,
        connector: str,
        items: Sequence[GrantItem],
        by: str,
        world_owner: str,
        at: str,
    ) -> DataGrant:
        if by != world_owner:
            raise HandoffRefused("DG-01", "only the world's owner makes a grant")
        partner = self._partners.get(connector) if isinstance(connector, str) else None
        if partner is None:
            raise HandoffRefused("DG-01", "the connector is not a configured build partner")
        items = tuple(items)
        if not 1 <= len(items) <= partner.max_items:
            raise HandoffRefused("DG-01", f"a grant names 1 to {partner.max_items} items")
        for item in items:
            if (problem := _item_problem(item)) is not None:
                raise HandoffRefused("DG-01", problem)
        if len({(i.kind, i.ref, i.version) for i in items}) != len(items):
            raise HandoffRefused("DG-01", "an item is named twice")
        with self._lock:
            grant_id = self._new_id()
            grant = DataGrant(grant_id, world_id, run_id, connector, items, by, at, "active", None, None)
            self._grants[grant_id] = grant
            return grant

    def _new_id(self) -> str:
        while (grant_id := "dg_" + "".join(secrets.choice(_CROCKFORD) for _ in range(26))) in self._grants:
            pass
        return grant_id

    def revoke(self, grant_id: str, *, by: str, world_owner: str, at: str) -> DataGrant:
        if by != world_owner:
            raise HandoffRefused("DG-01", "only the world's owner revokes a grant")
        with self._lock:
            grant = self._grants.get(grant_id)
            if grant is None:
                raise HandoffRefused("DG-03", f"grant {safe_id(grant_id)} is not known")
            if grant.state != "active":
                return grant
            self._grants[grant_id] = grant = dataclasses.replace(grant, state="revoked", ended_at=at, ended_by=by)
            return grant

    def end_run(self, world_id: str, run_id: str, *, at: str) -> tuple[DataGrant, ...]:
        """The task ended: every active grant of this run expires for good. Returns the ones that just did."""
        with self._lock:
            ended = []
            for grant_id, grant in list(self._grants.items()):
                if grant.state == "active" and (grant.world_id, grant.run_id) == (world_id, run_id):
                    self._grants[grant_id] = expired = dataclasses.replace(grant, state="expired", ended_at=at)
                    ended.append(expired)
            return tuple(ended)

    def get(self, grant_id: str) -> DataGrant | None:
        with self._lock:
            return self._grants.get(grant_id) if isinstance(grant_id, str) else None

    def require_active(self, grant_id: str, *, world_id: str, run_id: str, connector: str) -> DataGrant:
        """DG-03: a grant gives data only while active, for its own world, run and connector."""
        grant = self.get(grant_id)
        if grant is None or grant.state != "active":
            raise HandoffRefused("DG-03", f"grant {safe_id(grant_id)} is not active")
        if (grant.world_id, grant.run_id, grant.connector) != (world_id, run_id, connector):
            raise HandoffRefused("DG-03", f"grant {safe_id(grant_id)} is not for this task and partner")
        return grant


class TextArtifacts(Protocol):  # the artifact store's read side, scoped by world
    def head(self, world_id: str, ref: Mapping[str, Any]) -> Mapping[str, Any] | None: ...
    def read(self, world_id: str, ref: Mapping[str, Any]) -> bytes: ...  # hash-checked bytes (AR-01)


@dataclass(frozen=True)
class ExcerptRequest:
    ref: str  # artifact id
    version: int
    text: str | None  # a contiguous part of that version's text; None = the whole text


@dataclass(frozen=True)
class Excerpt:
    item: GrantItem
    text: str  # line endings normalised to LF, then the redactor's output
    redacted: bool  # the redactor changed it


def granted_excerpts(
    *,
    grants: GrantStore,
    artifacts: TextArtifacts,
    grant_id: str,
    world_id: str,
    run_id: str,
    connector: str,
    requests: Sequence[ExcerptRequest],
    partner: BuildPartnerConfig,
    redact: Callable[[str], str],
    safety: Screen,
) -> tuple[Excerpt, ...]:
    """The excerpts of granted items only, or a refusal; nothing is returned on a refusal."""
    grant = grants.require_active(grant_id, world_id=world_id, run_id=run_id, connector=connector)  # DG-03 first
    wanted = []
    for request in requests:  # DG-02, before artifacts.head or artifacts.read is called for any ref
        item = next(
            (
                i
                for i in grant.items
                if i.kind == "artifact"
                and i.ref == request.ref
                and i.version == request.version
                and type(request.version) is int
            ),
            None,
        )
        if item is None:
            raise HandoffRefused("DG-02", f"{safe_id(request.ref)} is not an item of grant {grant.id}")
        wanted.append((item, request))
    if len({(i.ref, i.version) for i, _ in wanted}) > partner.max_items:
        raise HandoffRefused("DG-04", f"at most {partner.max_items} distinct items per handoff")
    return tuple(_excerpt(artifacts, world_id, item, request, partner, redact, safety) for item, request in wanted)


def _excerpt(
    artifacts: TextArtifacts,
    world_id: str,
    item: GrantItem,
    request: ExcerptRequest,
    partner: BuildPartnerConfig,
    redact: Callable[[str], str],
    safety: Screen,
) -> Excerpt:
    ref = {"artifact_id": item.ref, "version": item.version}
    head = artifacts.head(world_id, ref)
    shown = safe_id(item.ref)
    if (
        not isinstance(head, Mapping)
        or head.get("world_id") != world_id
        or head.get("media_type") not in _TEXT_TYPES
        or head.get("screening") != "clean"
        or {k: (head.get("artifact") or {}).get(k) for k in ref} != ref
    ):
        raise HandoffRefused("DG-04", f"{shown} is not a clean text version of this world")
    raw = artifacts.read(world_id, ref)
    try:
        if hashlib.sha256(raw).hexdigest() != head.get("content_sha256"):
            raise ValueError
        whole = raw.decode("utf-8")  # strict
    except (ValueError, TypeError):
        raise HandoffRefused("DG-04", f"{shown} is not intact UTF-8 text") from None
    part = whole if request.text is None else request.text
    if not isinstance(part, str) or not part or part not in whole:
        raise HandoffRefused("DG-04", f"the requested part is not a part of {shown}")
    part = part.replace("\r\n", "\n").replace("\r", "\n")
    if len(part) > partner.max_excerpt_chars:
        raise HandoffRefused("DG-04", f"the excerpt of {shown} is over {partner.max_excerpt_chars} characters")
    try:
        clean = redact(part)
    except Exception:
        clean = ""
    if not isinstance(clean, str) or not clean or flagged(safety, clean):  # DG-05: the screen sees redacted text
        raise HandoffRefused("DG-05", f"the excerpt of {shown} did not pass the redactor and the safety screen")
    return Excerpt(item=item, text=clean, redacted=clean != part)
