# Universal intake and personal context — 12 October 2026

Status: product-owner requirement supplement, distilled from
`agy-bridge/tasks/SPEC-UNIVERSAL-INTAKE-AND-CONTEXT-PANEL.md` and the
12 October 07:00 supervisor NOTICE. The frozen PRD remains unchanged.
Contracts remain authoritative; proposed schemas, events and slice IDs require
the applicable ADR acceptance before implementation. This document does not
approve them or claim that the complete live experience is available.

## Product intent

People should be able to give Tilo data alongside their prompt and have its
Director, agents, skills and memory use that knowledge with citations.
A right-side panel should expose their projects, workspace and past, present
and future work. Both experiences must use recorded information, clearly
identify sample data in demo mode and say what is unavailable (HR-1..7).

## Universal intake requirement

The requested v1 inputs are text, paste, notes, voice notes and audio; PDFs,
images, scans, video and screen recordings; DOCX, PPTX, XLSX, CSV, TXT, MD,
JSON, HTML and capped ZIP archives; links and web pages; granted Google Drive,
email and calendar inputs; and meeting recordings and transcripts.
Each kind must work through the live path or give an explicit refusal and reason.
This list describes the requested coverage, not current availability.

The intended pipeline is add, validate size/type using magic bytes, archive raw
data with hash and provenance, screen for safety, select an extractor, normalize
the result, store cited knowledge in hybrid memory, and offer it to the Director
with a plain-language understanding card. Ambiguous inputs require a question
(FR-INT), never an inferred answer.

The proposed KnowledgeItem captures source, kind, title, summary, page/table/
timestamp structure, provenance, scope, consent, retention and cost. It is an
ADR proposal, not an existing approved contract. The composer should support
Add anything, drop and paste, Reading/Understood/Couldn't read status, a preview,
removal of derived data and a cost notice before large media.

Uploaded files are data, never executable instructions (SEC-05). Refuse macros
and archive bombs; never handle passwords. Enforce scope on the server, meter
reads within run and lifetime caps, and require T3 approval for anything that
leaves Tilo. Removal must cover archive-derived items and memory entries.

Draft acceptance checks: supported-kind fixtures produce summaries with page
or timestamp citations; unknown types fail honestly; planted prompt injection
is dropped and logged; deletion removes derived archive/memory items; large
media shows its cost line; another person cannot read the first person's item.
These checks require implementation evidence before completion is claimed.

## Context panel P1 as built

The implementation is in `apps/web/src/park/shell/ContextPanel.tsx`, its CSS,
and `ContextPanel.P1.test.tsx`. On the observed `phase0-stack` base
`3dcefc0a9e0d4da70ddab0ad37c4409b980c3908`, P1:

- Opens from the Park top bar or Alt+Shift+C, excluding editable controls.
  Open/closed preference is stored per person, with in-page fallback if storage fails.
- Uses an accessible popover with a close control, a right-side desktop panel
  and a bottom sheet on phone widths; styling uses existing role tokens.
- Reads existing worlds, decisions, agenda, team, connectors, skills and Ledger
  API methods independently. Read failures say not available, loading is visible,
  empty results say no recorded items, and fixture sections say Sample data.
- Shows running worlds, unanswered decisions and today's agenda under Now.
- Shows the selected world's name, state, recorded spend, plan/output where
  supplied and its decisions under This project; otherwise asks to open a project.
- Shows team, connected-tool state and skill state under Workspace.
- Shows finished worlds and recorded Ledger activity under Past; scheduled worlds
  and later agenda items under Future. A truncated live agenda is labelled partial.
- Explicitly marks agent/source details, memory explanations, routine next-run
  times, forecasts and KnowledgeItems as unavailable.

P1 is a read-only composition of existing API methods. It does not provide
KnowledgeItem creation/removal or assert that all requested context fields are
available live. This supplement records code behavior, not new deployment QA.

## Remaining slices and holds

| Slice | Requested outcome | Remaining dependency or limit |
| --- | --- | --- |
| I1 | KnowledgeItem/schema ADR | Universal-intake ADR-0036 (#843) remains proposed pending user acceptance. |
| I2/I3 | Upload/status and native extraction | Complete the approved existing-contract live path; a client seam alone is not end-to-end intake. |
| I4 | Deterministic document/archive parsing | Parser drafts and children remain subject to the assigned security review before integration. |
| I5 | Cited memory and Director prompt attachment | Approved knowledge representation, scope, deletion and attachment integration. |
| I6 | Composer and status UI | #854 supplies a gated-off client/UI seam; upload and Director attachment availability must be confirmed before enabling. |
| I7 | Evals and judge-path checklist | Evidence for supported kinds, refusal, injection handling, deletion, scope and costs. |
| P2 | One read-only GET /v1/context | #851 remains held for assigned security review; P1 does not consume it. |
| P3 | Knowledge section with source/scope/remove | I5 and the approved knowledge lifecycle. |
| P4 | Clearly labelled future expectations | A recorded, scoped forecast source; do not invent suggestions or next-run times. |

The 03:00 owner-scope ruling for P2 is caller-owned and fail-closed: eligible
pins belong to the caller by `set_up_by`, private `scope.user`, or source-world
ownership; work items are caller-assigned/created; meetings are caller-owned;
worlds require ownership or a share grant. Exclude other people's team-visible
items, names and email. Workspace aggregation permits only the caller's role
and org ID plus existing owner-route connector/skill state. Negative tests must
verify these boundaries before the aggregate is enabled.

Related Skills work (SKL-05/06/07) remains held under the 07:00 NOTICE.
Run/answer provenance ADR #856 awaits the user and architect lane; draft fix
#860 is not evidence of a deployed ratings, trust, pause or helper-count flow.
