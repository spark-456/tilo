# Provenance manifest — public API these tests pin (FR-CON-10)

Lane CL-REACH (`docs/lanes.md`). Tests: `test_FR_CON_10_provenance_manifest.py`; doubles in
`_provenance_lib.py`. Contract: `contracts/manifest.schema.json` (`tilo_contracts.Manifest`) and
MF-01 to MF-06 in `contracts/manifest.rules.md`; refs per BQ-59. The render side (the appendix in
the PDF or PPTX, AGR-04) and the artifact store that keeps the manifest with the version (P7) consume
this output; they are not tested here. Every test fails today with
`ModuleNotFoundError: tilo_connectors.provenance`.

## `tilo_connectors.provenance`

```python
class ManifestRefused(ValueError):
    rule: str  # "MF-01".."MF-06", "schema", or another short id for a broken archive chain
    # The message never contains the string the redactor flagged (MF-06).

def build_manifest(
    *,
    run_id: str,                       # the run that produced the version
    artifact: Mapping,                 # artifact_ref of this version
    content: bytes,                    # the version's stored bytes
    parents: Sequence[Mapping],        # artifact_refs; each an earlier version of the same artifact (MF-02)
    agent: Mapping,                    # {"agent_id", "role", "model_role", "profile"}
    inputs: Sequence[Mapping],         # artifact_refs the producer read
    sources: Sequence[Mapping],        # [{"id": slug, "archive_ref": "<run_id>/<seq>"}]
    claims: Sequence[Mapping],         # manifest claims: {"id", "location", "text", "source_ids", "verified"}
    events: Sequence[Mapping],         # TiloEvent dicts of the run that caused this version, any order
    archive: Sequence[Mapping],        # the run's raw-archive records (tilo_archive RunArchive.records())
    redact: Callable[[str], str],      # the shared secret redactor (SEC-14)
) -> dict                              # a Manifest document (plain JSON), or raises ManifestRefused
```

Pure and deterministic: no clock, no I/O, inputs never mutated. Same inputs give byte-identical
canonical JSON, whatever the order of `events`, `sources`, `claims` and each claim's `source_ids`.

### What it builds

- `content_sha256` = SHA-256 hex of `content`.
- `produced_by` = `agent` plus `skill`: `{"id": data.skill, "version": data.version}` of the
  `skill.loaded` event in `events` whose `actor` is `agent_id`; null when there is none (MF-05).
- Each source comes from the archive record its `archive_ref` names, never from the caller:
  `kind` and `ref` from the record's `payload.source`, `fingerprint` = `"sha256:" +` SHA-256 hex of
  `payload.content` encoded UTF-8, `fetched_at` = the record's `ts`. A `web` ref drops user info,
  query, fragment and `;` path parameters (MF-03, BQ-59). Source content is never copied.
- `sources` sorted by `id`; `claims` sorted by `id`, each `source_ids` sorted; `events` = ids
  ordered by `seq` (oldest first), duplicates removed.
- `authz` = the `authz` of a `data.transfer` in `events` with `data.direction == "out"` and
  `data.artifact` equal to `artifact` (MF-04, HR-7); null otherwise.

### Source-read archive record (pinned here; the archive payload is not in `contracts/`)

A `tool_call` record whose payload is
`{"tool": slug, "source": {"kind": "web"|"file"|"connector"|"cell"|"artifact", "ref": str}, "content": str}`.
`ref` is as read (a web URL may still hold a query); `content` is the text read, after the
archive's redactor.

### Refusals (`ManifestRefused.rule`)

| Rule | When |
| --- | --- |
| MF-01 | duplicate source id; a claim cites an id not in `sources` |
| MF-02 | a parent of another artifact or not an earlier version |
| MF-03 | a `cell`/`artifact` source whose `<artifact_id>@<version>` is not in `inputs` |
| MF-04 | an event of another run |
| MF-06 | `redact` would change any `ref`, `location` or `text` (every one is passed to it) |
| schema | the result does not validate against `manifest.schema.json` |
| any | an `archive_ref` that names no record, a non-`tool_call` record or another run's record; archive records of another run; a broken hash chain (`tilo_archive.verify_chain` reports a problem) |

Wiring the builder needs: `tilo-archive` and `tilo-contracts` as workspace dependencies of
`tilo-connectors`.
