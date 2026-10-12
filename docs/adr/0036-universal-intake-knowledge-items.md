# ADR-0036: Universal intake and sourced knowledge items

- Status: Proposed; requires user acceptance before any contract or event change.
- Decider: user; author: CX-LIVEWEB, 12 October 2026.
- Requirement: product-owner specification `agy-bridge/tasks/SPEC-UNIVERSAL-INTAKE-AND-CONTEXT-PANEL.md`;
  existing FR-INT-01/02/03/05/14, FR-MEM-05/09/12, FR-MTG-17, SEC-05, PL-01, EFF-01/03, HR-1..7.
- Related: ADR-0018 artifacts, ADR-0029 native media/fetch, ADR-0030 hybrid memory, ADR-0035 connectors.

## Proposal

Every added source becomes an owner-scoped, sourced, deletable KnowledgeItem. The user sees what was read,
what could not be read, and why. An accepted artifact is not evidence that Tilo understood its contents.
Use existing contracts for independently shippable upload/native-reading slices; do not represent a
KnowledgeItem as an untyped JSON artifact to evade schema approval.

Proposed contract, not an implementation or an accepted schema:

```text
KnowledgeItem {
  id, owner_id, org_id, world_id?,
  source: {kind, artifact_ref?, connector_ref?, archive_ref?},
  kind, title, status: reading | understood | unreadable, reason?,
  summary?, structure: [{page?, timestamp_start_ms?, timestamp_end_ms?, table?, text}],
  provenance: {sha256?, received_at, extractor_version, source_refs},
  scope: private | world | team,
  consent: {purpose, granted_at, connector_scopes},
  retention: {policy, expires_at?, deleted_at?},
  cost: {estimated_credits?, actual_credits?}
}
```

Code assigns identity, scope, provenance and status. Models may produce bounded summaries/structure only.
Structure entries cite a real page, timestamp or recorded text source; missing evidence is explicit.
Scope expansion needs approval of the access policy. Raw and derived deletion must share an erasure index.

## Existing seams and exact coverage

| Input | Existing contract/seam | Coverage and remaining limit |
| --- | --- | --- |
| Prompt, paste, notes | `POST /intake`; `brief.schema.json`; `tilo_planning.intake` | Screened task text, bounded to 4,000 characters; not a separately retained knowledge item. |
| PDF, PNG, JPEG, scans | Intake extraction and native safety; providers `MediaPart`, `GenerateRequest.parts`; `artifact.schema.json` | Existing native reading supports PDF/image requests; current intake Director receives task text only. |
| DOCX, PPTX, XLSX, CSV | `tilo_planning.extraction`; existing artifact media enum | Bounded text conversion exists; no normalized page/table summaries. I4 parser hardening is assigned separately. |
| TXT, MD, JSON, HTML files | Artifact enum supports Markdown/JSON, not plain text/HTML; upload extension allowlist excludes all four | Existing storage media does not imply intake support; HTML/SVG remain excluded. |
| Audio, voice notes | `SpeechProvider.transcribe`; voice-intake seam; native provider audio parts | General upload artifact enum has no audio types; voice transcription does not establish reusable file knowledge. |
| Video, screen recordings | Providers video parts; artifact WebM/MP4 for taught-skill capture only | Existing contract restricts storage to capture; general intake video needs an accepted change. |
| Public links/web pages | `brief.sources` url/web; `tilo_browser.FetchService`; run-scoped raw archive | Bounded screened fetch and native source handoff in the live-web integration; not a persistent KnowledgeItem. |
| ZIP | No intake/archive-expansion contract | Not accepted; I4 pure parser library must receive security review before route wiring. |
| Drive, email, calendar | Brief connector sources; ADR-0035 connector adapters and grant checks | Granted connector reads exist; no generic picker-to-knowledge import or retention mapping. |
| Meetings/transcripts | `meeting.schema.json`, `transcript.schema.json`; FR-MTG-17 meeting path | Meeting-scoped evidence exists; reusable knowledge ingestion/deletion remains separate. |

`artifact.created` can report an existing uploaded artifact, with a factual summary; it cannot encode
KnowledgeItem lifecycle fields. `brief.sources` represents file/url/connector/web/memory references, not
page/time structure. The planning upload store is in memory and separate from the run artifact store;
a file reference in the brief alone does not bridge its bytes into the production harness.
ADR-0030 proposes hybrid retrieval; this ADR does not claim that retrieval is deployed.

## Slices and approval boundary

Proposed IDs: UNI-INT-I1 (this ADR), I2 (existing upload/archive/status), I3 (native extraction), I4 (bounded
document parsers), I5 (memory and prompt attachment), I6 (composer/status UI), I7 (per-kind evals).
I2 must retain current limits, magic/extension agreement, screening, principal ownership and refusal events.
I3 may read only screened PDF/PNG/JPEG through providers, with existing byte/page/token budgets and data
delimiters; unconfirmed extraction is unreadable. Never add a model identifier outside configuration.

Approval needed: `knowledge_item.schema.json` and rules/fixtures; registered created/understood/unreadable/
deleted lifecycle events and data schemas; accepted source provenance/page/timestamp shapes; erasure index
coverage; policies for scope, consent, retention and media-cost confirmation. General audio/video and HTML/
ZIP intake require explicit media/source policy decisions. Until accepted, use existing artifact/source
contracts and honestly name unsupported kinds; do not add new schema fields or event types.

## Acceptance and rollout

Tests carry slice and existing requirement IDs: per-kind citation, unreadable type, injection refusal,
owner isolation, raw/derived erasure, media-cost confirmation, and missing-provider failures. Use fake or
recorded providers locally; no paid calls or LIVE. A slice is ready after affected gates and one repo gate
per push group; it is live only after coordinator deployment and signed-in acceptance with recorded evidence.
