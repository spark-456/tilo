# Manifest rules beyond the schema (manifest.schema.json v1)

PRD 13.3: a provenance manifest links an artifact version to what produced it, and "Why is
this here?" follows a claim to its sources and its first causing event (FR-MEM-07).
`manifest.schema.json` checks one document; the artifact store checks these rules before it
writes a version's manifest, and MF-06 again before any export (P7 validator tests cover them).
Rule ids are stable.

| Rule | Rule | Checked by | Source |
| --- | --- | --- | --- |
| MF-01 | `sources[].id` are unique, `claims[].id` are unique, and every `claims[].source_ids` entry names a source of the same manifest. A verified claim names at least one source. | validator (schema for verified claims) | 13.3 |
| MF-02 | `content_sha256` is the SHA-256 of the version's stored bytes. Each of `parents` is an earlier version of the same `artifact_id`; a restore (FR-MEM-06) names the version it restores. | validator | 13.2, 13.4 |
| MF-03 | A `cell` source's `ref` is `<artifact_id>@<version>#<cell>` and an `artifact` source's is `<artifact_id>@<version>`, naming a version in `inputs`; a `web` source's `ref` is the http or https URL it was fetched from, recorded without user info, query, fragment or path parameters (BQ-59). The schema allows only four closed shapes (an http or https URL of host, optional port and path, the path without `;` or `=`; an artifact ref with an optional cell of letters, digits and `. _ ~ ! : $ -`; a `<connector_id>:<item id>` of letters, digits and `. _ ~ -`; a file name with no `/ \ : ? # @ %`, control character or space at either end), so user info in any spelling (`//u@host`, `https:\u@host`, `https:u@host`, a leading space) and query, fragment, path-parameter and cell tokens (`?access_token=`, `#access_token=`, `;access_token=`, `@2#access_token=`) fail. A bare token can still pass as a file name or an item id; MF-06 catches it. Which shape each `kind` uses is the validator's. | validator (schema for the four shapes) | 13.3, 16.1, 16.2 |
| MF-04 | `events` are events of the run that produced the version, oldest first. `authz`, when set, equals the `authz` of a side-effect event in `events` that carried this version out of Tilo (HR-7); it is null when the version never left Tilo. | validator | 13.3, 10.4 |
| MF-05 | `produced_by.skill` is the version the run pinned for that agent (`skill.loaded`, FR-AGT-03); `model_role` and `profile` are names from `config/models.yaml`, never a model id (PL-01). | validator (schema for name shapes) | 8.2, 13.3 |
| MF-06 | Before the artifact store writes a manifest, and again before an export or a run bundle carries one out of Tilo (13.3, 13.4), the secret redactor that guards the raw archive (16.2, SEC-14) scans every string in it (each `ref`, `location` and `text`). A manifest the redactor would change is refused, never stored or exported: the producer records the source again without the secret, or leaves it out. SEC-01's secret scan of stores covers stored manifests. | validator (redactor) | 13.3, 13.4, 16.1, 16.2, SEC-01, SEC-14 |
