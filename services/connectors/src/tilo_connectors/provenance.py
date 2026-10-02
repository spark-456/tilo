"""tilo_connectors.provenance — the provenance manifest of one deliverable version (FR-CON-10).

PRD 12.4, 13.2, 13.3; `contracts/manifest.schema.json` and MF-01 to MF-06 in
`contracts/manifest.rules.md`; API pinned in `tests/API_FR_CON_10.md`. Pure and deterministic: no
clock, no I/O, inputs never mutated. A source's ref, hash and time come only from the run's
raw-archive record the caller names, and no source content is ever copied into the manifest.
Refusal messages name a rule and a position, never a caller value. Caller types, the size caps and
repeated refs are checked in linear time before any schema check (#187).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from tilo_archive import verify_chain
from tilo_contracts import Manifest

from ._schema import manifest_validator

_ARCHIVE_SEQ = re.compile(r"[1-9][0-9]{0,17}")
_ARTIFACT_REF = re.compile(r"(art_[0-9A-Za-z_]{1,48})@([1-9][0-9]{0,8})(#.*)?", re.DOTALL)
_CAPS = {"parents": 1000, "inputs": 5000}  # BQ-106: jsonschema never sees a longer list
_DIGESTS = frozenset({"content_sha256", "fingerprint"})  # hex digests; the redactor gets every other string


class ManifestRefused(ValueError):
    """`rule` is "MF-01".."MF-06", "schema" or "archive" (a source read the archive does not hold,
    or an archive of another run, with a broken hash chain or not ending at `archive_head`)."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(f"{rule}: {message}")
        self.rule = rule


def _key(ref: Any) -> tuple[str, int] | None:
    """(artifact_id, version), type-strict: version True or 1.0 never matches 1; None when malformed."""
    if isinstance(ref, Mapping) and type(ref.get("artifact_id")) is str and type(ref.get("version")) is int:
        return ref["artifact_id"], ref["version"]
    return None


def _check_caller(
    artifact: Any, content: Any, agent: Any, refs: dict[str, Any], head: Any
) -> dict[str, set[tuple[str, int] | None]]:
    """Caller types, the caps and repeated (artifact_id, version) refs; returns the ref keys by field."""
    if _key(artifact) is None or not isinstance(agent, Mapping) or not isinstance(content, bytes | bytearray):
        raise ManifestRefused("schema", "artifact must be an artifact ref, agent an object and content bytes")
    if head is not None and not (
        isinstance(head, tuple) and len(head) == 2 and type(head[0]) is int and isinstance(head[1], str)
    ):
        raise ManifestRefused("schema", "archive_head must be a (seq, hash) pair")
    keys = {}
    for field, items in refs.items():
        if not isinstance(items, list | tuple) or len(items) > _CAPS[field]:
            raise ManifestRefused("schema", f"{field} must be a list of at most {_CAPS[field]} refs")
        keys[field] = {_key(item) for item in items}
        if None in keys[field]:
            raise ManifestRefused("schema", f"every {field} entry needs a string artifact_id and an integer version")
        if len(keys[field]) != len(items):
            raise ManifestRefused("schema", f"{field} names the same artifact version twice")
    return keys


def _ids(items: Sequence[Mapping], what: str) -> list[str]:
    ids = [item.get("id") if isinstance(item, Mapping) else None for item in items]
    if not all(isinstance(i, str) for i in ids):
        raise ManifestRefused("schema", f"every {what} must be an object with a string id")
    if len(set(ids)) != len(ids):
        raise ManifestRefused("MF-01", f"duplicate {what} id")
    return ids  # type: ignore[return-value]


def _records_by_seq(run_id: str, archive: Sequence[Mapping], head: tuple[int, str] | None) -> dict[int, dict]:
    if not all(isinstance(record, Mapping) for record in archive):
        raise ManifestRefused("archive", "an archive record is not an object")
    records = [dict(record) for record in archive]
    if any(record.get("run_id") != run_id for record in records):
        raise ManifestRefused("archive", "the archive holds records of another run")
    problems = verify_chain(records, expected_head=head)  # head: from an anchor outside the archive (#187)
    if problems:
        raise ManifestRefused("archive", f"the archive hash chain is broken ({len(problems)} problem(s))")
    return {record["seq"]: record for record in records}


def _web_ref(url: str, where: str) -> str:
    """The fetched URL without user info, query, fragment or `;` path parameters (MF-03, BQ-59)."""
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise ManifestRefused("MF-03", f"{where}: web ref is not a URL") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not host:
        raise ManifestRefused("MF-03", f"{where}: web ref is not an http or https URL")
    path = "/".join(segment.split(";", 1)[0] for segment in parts.path.split("/"))
    return f"{scheme}://{host if port is None else f'{host}:{port}'}{path}"


def _source(
    index: int, entry: Mapping, run_id: str, by_seq: Mapping[int, dict], inputs: set[tuple[str, int] | None]
) -> dict[str, Any]:
    where = f"sources[{index}]"
    run, _, seq = str(entry.get("archive_ref", "")).rpartition("/")
    record = by_seq.get(int(seq)) if run == run_id and _ARCHIVE_SEQ.fullmatch(seq) else None
    payload = record.get("payload") if record is not None and record.get("kind") == "tool_call" else None
    read = payload.get("source") if isinstance(payload, dict) else None
    content = payload.get("content") if isinstance(payload, dict) else None
    if (
        record is None
        or not isinstance(read, dict)
        or not isinstance(read.get("ref"), str)
        or not isinstance(content, str)
    ):
        raise ManifestRefused("archive", f"{where}: archive_ref names no source read of this run")
    kind, ref = read.get("kind"), read["ref"]
    if kind == "web":
        ref = _web_ref(ref, where)
    elif kind in ("cell", "artifact"):
        match = _ARTIFACT_REF.fullmatch(ref)
        if (
            match is None
            or (match.group(3) is None) != (kind == "artifact")
            or (match.group(1), int(match.group(2))) not in inputs
        ):
            raise ManifestRefused("MF-03", f"{where}: a {kind} source must name an artifact version in inputs")
    return {
        "id": entry["id"],
        "kind": kind,
        "ref": ref,
        "fingerprint": "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "fetched_at": record["ts"],
    }


def _claim(index: int, claim: Mapping, source_ids: set[str]) -> dict[str, Any]:
    cited = claim.get("source_ids")
    if not isinstance(cited, list | tuple) or not all(isinstance(i, str) for i in cited):
        raise ManifestRefused("schema", f"claims[{index}]: source_ids must be a list of ids")
    if not set(cited) <= source_ids:
        raise ManifestRefused("MF-01", f"claims[{index}] cites a source that is not in sources")
    return {
        "id": claim["id"],
        "location": claim.get("location"),
        "text": claim.get("text"),
        "source_ids": sorted(cited),
        "verified": claim.get("verified"),
    }


def _ordered_events(run_id: str, events: Sequence[Mapping]) -> list[Mapping]:
    for event in events:
        if not isinstance(event, Mapping) or not all(
            isinstance(part, Mapping) for part in (event.get("data") or {}, event.get("authz") or {})
        ):
            raise ManifestRefused("schema", "an event, its data or its authz is not an object")
        if event.get("run_id") != run_id:
            raise ManifestRefused("MF-04", "an event of another run")
        if not isinstance(event.get("seq"), int) or not isinstance(event.get("id"), str):
            raise ManifestRefused("MF-04", "an event without an integer seq and a string id")
    return sorted(events, key=lambda event: (event["seq"], event["id"]))


def _skill(agent_id: Any, events: Sequence[Mapping]) -> dict[str, Any] | None:
    """The latest `skill.loaded` of the producing agent (MF-05); None when it loaded none."""
    loaded = [e.get("data") or {} for e in events if e.get("type") == "skill.loaded" and e.get("actor") == agent_id]
    return {"id": loaded[-1].get("skill"), "version": loaded[-1].get("version")} if loaded else None


def _authz(artifact: Mapping, events: Sequence[Mapping]) -> dict[str, Any] | None:
    """The authz of the first send that carried this version out of Tilo (MF-04, HR-7)."""
    for event in events:
        data = event.get("data") or {}
        if (
            event.get("type") == "data.transfer"
            and data.get("direction") == "out"
            and _key(data.get("artifact")) == _key(artifact)
            and event.get("authz") is not None
        ):
            return dict(event["authz"])
    return None


def _check_schema(manifest: dict[str, Any]) -> None:
    paths = sorted({"/".join(map(str, e.absolute_path)) for e in manifest_validator().iter_errors(manifest)})
    if paths:
        raise ManifestRefused("schema", "does not match manifest.schema.json at: " + ", ".join(paths))
    try:
        Manifest.model_validate(manifest)
    except ValueError:  # pydantic's ValidationError; its text echoes values, so it is not chained
        raise ManifestRefused("schema", "does not match tilo_contracts.Manifest") from None


def _strings(value: Any, where: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield where, value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in _DIGESTS:
                yield from _strings(item, f"{where}.{key}" if where else key)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _strings(item, f"{where}[{i}]")


def _check_redaction(manifest: dict[str, Any], redact: Callable[[str], str]) -> None:
    """MF-06: refused when the shared secret redactor would change any string but a hex digest."""
    for where, text in _strings(manifest):
        try:
            changed = redact(text) != text
        except Exception:
            changed = True  # fail closed; the redactor's message may echo the text
        if changed:
            raise ManifestRefused("MF-06", f"{where} holds what the secret redactor removes; record it without it")


def build_manifest(
    *,
    run_id: str,
    artifact: Mapping,
    content: bytes,
    parents: Sequence[Mapping],
    agent: Mapping,
    inputs: Sequence[Mapping],
    sources: Sequence[Mapping],
    claims: Sequence[Mapping],
    events: Sequence[Mapping],
    archive: Sequence[Mapping],
    redact: Callable[[str], str],
    archive_head: tuple[int, str] | None = None,
) -> dict[str, Any]:
    """The Manifest document of one artifact version, or ManifestRefused (tests/API_FR_CON_10.md).
    Production callers must pass `archive_head` from an anchor outside the archive's own bucket."""
    keys = _check_caller(artifact, content, agent, {"parents": parents, "inputs": inputs}, archive_head)
    by_seq = _records_by_seq(run_id, archive, archive_head)
    artifact_id, own = artifact["artifact_id"], artifact["version"]
    if any(key is None or key[0] != artifact_id or key[1] >= own for key in keys["parents"]):
        raise ManifestRefused("MF-02", "a parent is not an earlier version of the same artifact")
    ordered = _ordered_events(run_id, events)
    source_ids = set(_ids(sources, "source"))
    _ids(claims, "claim")
    built_sources = [_source(i, s, run_id, by_seq, keys["inputs"]) for i, s in enumerate(sources)]
    built_claims = [_claim(i, c, source_ids) for i, c in enumerate(claims)]
    manifest: dict[str, Any] = {
        "v": "1.0",
        "artifact": dict(artifact),
        "content_sha256": hashlib.sha256(bytes(content)).hexdigest(),
        "parents": [dict(ref) for ref in parents],
        "produced_by": {
            "agent_id": agent.get("agent_id"),
            "role": agent.get("role"),
            "skill": _skill(agent.get("agent_id"), ordered),
            "model_role": agent.get("model_role"),
            "profile": agent.get("profile"),
        },
        "inputs": [dict(ref) for ref in inputs],
        "sources": sorted(built_sources, key=lambda s: s["id"]),
        "claims": sorted(built_claims, key=lambda c: c["id"]),
        "events": list(dict.fromkeys(event["id"] for event in ordered)),
        "authz": _authz(artifact, ordered),
    }
    _check_schema(manifest)  # before the redactor (BQ-106): it only ever sees well-formed strings
    _check_redaction(manifest, redact)
    return manifest
