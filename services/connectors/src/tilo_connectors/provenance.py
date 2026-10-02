"""tilo_connectors.provenance — the provenance manifest of one deliverable version (FR-CON-10).

PRD 12.4, 13.2, 13.3; `contracts/manifest.schema.json` and MF-01 to MF-06 in
`contracts/manifest.rules.md`; API pinned in `tests/API_FR_CON_10.md`. Pure and deterministic: no
clock, no I/O, inputs never mutated. A source's ref, hash and time come only from the run's
raw-archive record the caller names, and no source content is ever copied into the manifest.
Refusal messages name a rule and a position, never a caller value.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from tilo_archive import verify_chain
from tilo_contracts import Manifest

from ._schema import manifest_validator

_ARCHIVE_SEQ = re.compile(r"[1-9][0-9]{0,17}")
_ARTIFACT_REF = re.compile(r"(art_[0-9A-Za-z_]{1,48})@([1-9][0-9]{0,8})(#.*)?", re.DOTALL)


class ManifestRefused(ValueError):
    """`rule` is "MF-01".."MF-06", "schema" or "archive" (a source read the archive does not hold,
    or an archive of another run or with a broken hash chain)."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(f"{rule}: {message}")
        self.rule = rule


def _key(ref: Mapping) -> tuple[Any, Any]:
    return ref.get("artifact_id"), ref.get("version")


def _ids(items: Sequence[Mapping], what: str) -> list[str]:
    ids = [item.get("id") for item in items]
    if not all(isinstance(i, str) for i in ids):
        raise ManifestRefused("schema", f"every {what} needs a string id")
    if len(set(ids)) != len(ids):
        raise ManifestRefused("MF-01", f"duplicate {what} id")
    return ids  # type: ignore[return-value]


def _records_by_seq(run_id: str, archive: Sequence[Mapping]) -> dict[int, dict]:
    records = [dict(record) for record in archive]
    if any(record.get("run_id") != run_id for record in records):
        raise ManifestRefused("archive", "the archive holds records of another run")
    problems = verify_chain(records)
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
    index: int, entry: Mapping, run_id: str, by_seq: Mapping[int, dict], inputs: set[tuple[Any, Any]]
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
        sent = data.get("artifact")
        if (
            event.get("type") == "data.transfer"
            and data.get("direction") == "out"
            and isinstance(sent, Mapping)
            and _key(sent) == _key(artifact)
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


def _check_redaction(manifest: dict[str, Any], redact: Callable[[str], str]) -> None:
    """MF-06: refused when the shared secret redactor would change any ref, location, text or label."""
    strings = [(f"sources[{i}].ref", s["ref"]) for i, s in enumerate(manifest["sources"])]
    for i, claim in enumerate(manifest["claims"]):
        strings += [(f"claims[{i}].location", claim["location"]), (f"claims[{i}].text", claim["text"])]
    refs = [("artifact", manifest["artifact"])]
    refs += [(f"{field}[{i}]", r) for field in ("parents", "inputs") for i, r in enumerate(manifest[field])]
    strings += [(f"{where}.label", ref["label"]) for where, ref in refs if "label" in ref]
    for where, text in strings:
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
) -> dict[str, Any]:
    """The Manifest document of one artifact version, or ManifestRefused (tests/API_FR_CON_10.md)."""
    by_seq = _records_by_seq(run_id, archive)
    for parent in parents:
        version, own = parent.get("version"), artifact.get("version")
        if not (
            parent.get("artifact_id") == artifact.get("artifact_id")
            and isinstance(version, int)
            and isinstance(own, int)
            and version < own
        ):
            raise ManifestRefused("MF-02", "a parent is not an earlier version of the same artifact")
    ordered = _ordered_events(run_id, events)
    source_ids = set(_ids(sources, "source"))
    _ids(claims, "claim")
    input_keys = {_key(ref) for ref in inputs}
    built_sources = [_source(i, s, run_id, by_seq, input_keys) for i, s in enumerate(sources)]
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
