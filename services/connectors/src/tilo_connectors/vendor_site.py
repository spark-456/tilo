"""tilo_connectors.vendor_site — vendor-facing sites (FR-CON-21, PRD supplement 2026-10-05 s6; an interpretation of
"3rd-party vendor side websites" that the user may refine).

A vendor-site brief is the person-accepted requirements of one deliverable plus a few closed-vocabulary sentences
(what vendors need, what the team tracks, how vendors get access); it then goes through the existing Lovable link
route (`handoff.prepare_handoff`, FR-CON-16/17: T3, a person approves, Tilo makes only a link). There is no free
text and no credential field anywhere in a spec: access is by invite or link from the site's own platform, and Tilo
never takes, types or stores a password (hard rule). Status is read from the run's raw archive only: the latest
recorded read of each page the person connected, or an honest "not read" (HR-1). No network, no model, no event
is emitted here. Pinned API: services/connectors/tests/API_FR_CON_21.md. FR-CON-18 (the MCP route) is not built.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from tilo_archive import verify_chain

from ._text import collapse, has_hidden, safe_id
from .errors import HandoffRefused
from .handoff import AcceptedRequirements, PreparedHandoff, prepare_handoff

NEEDS = {
    "submit_quote": "Vendors can submit a quote for the requirements.",
    "view_requirements": "Vendors can see the requirements they are asked to meet.",
    "confirm_order": "Vendors can confirm an order they receive.",
    "update_delivery": "Vendors can update the delivery status of an order.",
    "upload_invoice": "Vendors can upload an invoice for a delivered order.",
}
TRACKS = {
    "quotes": "The team can track the status of quotes.",
    "orders": "The team can track the status of orders.",
    "deliveries": "The team can track the status of deliveries.",
}
ACCESS = {
    "invite": "Vendors get access by an invitation from this site's own sign-in; no vendor account is set up here.",
    "link": "Vendors get access by a private link from this site's own sign-in; no vendor account is set up here.",
}
_KEYS = frozenset({"needs", "tracks", "access", "status_sources"})
_SOURCE_KEYS = frozenset({"id", "category", "kind", "ref"})
_SOURCE_ID = re.compile(r"[a-z][a-z0-9_]{1,31}")
_WEB = re.compile(r"https://[A-Za-z0-9.-]{1,253}(?:/[A-Za-z0-9._~/-]*)?", re.ASCII)
_CONNECTOR_REF = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
MAX_SOURCES = 6
_EXCERPT = 300


@dataclass(frozen=True)
class StatusSource:  # a page or API the person connected for tracking
    id: str
    category: str  # a key of TRACKS
    kind: str  # "web" | "connector"
    ref: str


@dataclass(frozen=True)
class VendorSiteSpec:
    needs: tuple[str, ...]
    tracks: tuple[str, ...]
    access: str
    status_sources: tuple[StatusSource, ...] = ()


def _refuse(rule: str, detail: str) -> HandoffRefused:
    return HandoffRefused(rule, detail)


def _chosen(raw: Any, vocabulary: Mapping[str, str], name: str, high: int) -> tuple[str, ...]:
    ok = isinstance(raw, list) and 1 <= len(raw) <= high and all(isinstance(v, str) for v in raw)
    if not ok or len(set(raw)) != len(raw) or any(v not in vocabulary for v in raw):
        raise _refuse("VS-02", f"{name} must be 1 to {high} distinct values from the fixed list")
    return tuple(raw)


def _source(raw: Any, tracks: tuple[str, ...]) -> StatusSource:
    if not isinstance(raw, Mapping):
        raise _refuse("VS-02", "a status source is a mapping")
    if extra := next((k for k in raw if k not in _SOURCE_KEYS), None):
        raise _refuse("VS-01", f"a status source holds only id, category, kind and ref, not {safe_id(extra)}")
    ident, category, kind, ref = (raw.get(k) for k in ("id", "category", "kind", "ref"))
    if not all(isinstance(v, str) for v in (ident, category, kind, ref)):
        raise _refuse("VS-02", "a status source needs an id, a category, a kind and a ref")
    source = StatusSource(str(ident), str(category), str(kind), str(ref))
    shape = {"web": _WEB, "connector": _CONNECTOR_REF}.get(source.kind)
    if shape is None or not _SOURCE_ID.fullmatch(source.id) or source.category not in tracks:
        raise _refuse("VS-02", "a status source needs a tracked category and a web or connector kind")
    if not shape.fullmatch(source.ref):
        raise _refuse("VS-02", "a status source ref is an https page without a query, or a connector ref")
    return source


def vendor_spec(raw: Mapping[str, Any]) -> VendorSiteSpec:
    """The closed spec, or HandoffRefused: VS-01 a field that is not in the list (a credential field is never
    one), VS-02 a value outside the fixed vocabulary or a bad status source. Values are never echoed."""
    if not isinstance(raw, Mapping):
        raise _refuse("VS-02", "a vendor site spec is a mapping")
    if extra := next((k for k in raw if k not in _KEYS), None):
        raise _refuse(
            "VS-01", f"a vendor site spec holds only needs, tracks, access and status_sources, not {safe_id(extra)}"
        )
    needs, tracks = (
        _chosen(raw.get("needs"), NEEDS, "needs", len(NEEDS)),
        _chosen(raw.get("tracks"), TRACKS, "tracks", 3),
    )
    access = raw.get("access")
    if not isinstance(access, str) or access not in ACCESS:
        raise _refuse("VS-02", "access is invite or link")
    sources_raw = raw.get("status_sources", [])
    if not isinstance(sources_raw, list) or len(sources_raw) > MAX_SOURCES:
        raise _refuse("VS-02", f"at most {MAX_SOURCES} status sources")
    sources = tuple(_source(s, tracks) for s in sources_raw)
    if len({s.id for s in sources}) != len(sources):
        raise _refuse("VS-02", "a status source id is used twice")
    return VendorSiteSpec(needs, tracks, access, sources)


def vendor_requirements(accepted: AcceptedRequirements, spec: VendorSiteSpec) -> AcceptedRequirements:
    """The accepted requirements plus the spec's fixed sentences: nothing else is added to what is sent."""
    added = (*(NEEDS[n] for n in spec.needs), *(TRACKS[t] for t in spec.tracks), ACCESS[spec.access])
    return dataclasses.replace(accepted, constraints=(*accepted.constraints, *added))


def prepare_vendor_site(*, accepted: AcceptedRequirements, spec: VendorSiteSpec, **handoff: Any) -> PreparedHandoff:
    """The Lovable handoff for a vendor site: `prepare_handoff` over `vendor_requirements` (BH-01..BH-09 apply)."""
    return prepare_handoff(accepted=vendor_requirements(accepted, spec), **handoff)


@dataclass(frozen=True)
class SourceStatus:
    source_id: str
    category: str
    state: str  # "read" | "not_read": nothing else is ever shown
    archive_ref: str | None  # "<run_id>/<seq>" of the recorded read
    read_at: str | None
    fingerprint: str | None
    excerpt: str | None  # the start of the text that was read, as the archive's redactor left it


@dataclass(frozen=True)
class VendorStatus:
    sources: tuple[SourceStatus, ...]


def vendor_status(
    spec: VendorSiteSpec,
    records: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    archive_head: tuple[int, str] | None = None,
) -> VendorStatus:
    """Per connected source, its latest recorded read, else "not_read". Only `tool_call` records of this run whose
    payload source is exactly a connected source count; a broken chain or another run's record is VS-03."""
    rows = [dict(r) for r in records if isinstance(r, Mapping)]
    if len(rows) != len(records) or any(r.get("run_id") != run_id for r in rows):
        raise _refuse("VS-03", "the archive holds a record that is not of this run")
    if verify_chain(rows, expected_head=archive_head):
        raise _refuse("VS-03", "the archive hash chain is broken")
    out = []
    for source in spec.status_sources:
        reads = [r for r in rows if r.get("kind") == "tool_call" and _reads(r.get("payload"), source)]
        if not reads:
            out.append(SourceStatus(source.id, source.category, "not_read", None, None, None, None))
            continue
        last = max(reads, key=lambda r: int(r["seq"]))
        text = last["payload"]["content"]
        out.append(
            SourceStatus(
                source.id,
                source.category,
                "read",
                f"{run_id}/{last['seq']}",
                last["ts"],
                "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "" if has_hidden(text) else collapse(text)[:_EXCERPT],
            )
        )
    return VendorStatus(tuple(out))


def _reads(payload: Any, source: StatusSource) -> bool:
    read = payload.get("source") if isinstance(payload, dict) else None
    return (
        isinstance(read, dict)
        and (read.get("kind"), read.get("ref")) == (source.kind, source.ref)
        and isinstance(payload.get("content"), str)
    )
