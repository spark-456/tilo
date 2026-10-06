# FR-AGT-15 interface the acceptance tests pin (harness + API; no UI)

PRD 8.2 "Teaching (Should)": a Team Lead's answer can be promoted into a proposed skill change for expert review.
PRD 10.5: the Team Lead console has a "Promote to skill" action. FR-AGT-15 acceptance: "The proposal appears for expert
review with a diff." Tests: `services/harness/tests/test_FR_AGT_15_*.py` (support `agt15_support.py`) and
`services/api/tests/test_FR_AGT_15_*.py` (support `_agt15_api_lib.py`).

## Harness: `tilo_harness.skill_proposals`

```python
class SkillProposalError(Exception):
    reason: str   # stable code, see the table

class SkillProposals:
    def __init__(self, registry: SkillRegistry, *, clock: Callable[[], str] | None = None) -> None
    def propose(self, *, decision: Mapping, skill_id: str, proposer: str, guidance: str | None = None) -> dict
    def get(self, proposal_id: str) -> dict | None
    def list(self, *, status: str | None = None) -> list[dict]          # oldest first
    def approve(self, proposal_id: str, *, reviewer: str, experts: Collection[str]) -> dict
    def reject(self, proposal_id: str, *, reviewer: str, experts: Collection[str], reason: str | None = None) -> dict
```

- In-memory store of proposals (like `CardStore`); the registry's folder is the skill store. `clock` returns an RFC 3339
  ms timestamp (`common.schema.json#/$defs/timestamp`); default is the real UTC clock.
- `decision` is a Decision (`contracts/decision.schema.json`), what tilo-api stores for a Team Lead's answer.
- `experts` is the set of user ids the caller (tilo-api) resolved as Team Leads of the skill's domain from current,
  owner-assigned records. `approve`/`reject` re-check it on every call.
- No model, provider or router anywhere in the module (a model never decides authorisation).

### Proposal (plain JSON data; `json.dumps` works; nothing but str, int, null, list, dict)

| field | meaning |
| --- | --- |
| `id` | `[A-Za-z0-9_-]{1,64}`, safe in a URL path |
| `status` | `proposed` -> `approved` or `rejected`; nothing else, and only a person's call moves it |
| `skill_id`, `domain` | the skill (its folder `skills/<domain>/<skill_id>/`) |
| `from_version`, `to_version` | skill.yaml versions; `to_version` is a larger plain semver |
| `base_sha256` | `LoadedSkill.sha256` of the skill when proposed; approval is refused (`stale`) if it moved on |
| `guidance` | the text promoted (the Team Lead's typed `guidance`, else the Decision's `answer`), stored as data |
| `proposed_body` | the full new SKILL.md text: the old body unchanged, with the guidance appended by code |
| `diff` | one unified diff of the skill before and after: a section for `SKILL.md` and one for `skill.yaml` (the version bump), each `--- a/...` / `+++ b/...`, hunks `@@`; applying the SKILL.md section to the old file gives `proposed_body` exactly |
| `provenance` | `decision_id` (which answer), `card_id`, `team_lead` (Team Lead id), `team_lead_user`, `world_id`, `run_id` (which run), `proposed_by`, `proposed_at` |
| `reviewed_by`, `reviewed_at` | null until approved or rejected |
| `review_note` | null, or the expert's `reject(reason=)` text (at most 500 characters, same text and secret checks as guidance), stored as data |

### Rules

| reason (on `SkillProposalError.reason`) | when |
| --- | --- |
| `invalid_decision` | the Decision does not validate against `decision.schema.json` |
| `not_team_lead_answer` | `answered_by.by` is not `team_lead` (an owner's answer is not promoted) |
| `not_the_answerer` | `proposer` is not `answered_by.user` |
| `unknown_skill` | `skill_id` is not in the registry, or is not a plain skill id (never a path: `../x`, `/`, `\`, upper case, empty) |
| `domain_mismatch` | the Decision's `domain` is not the skill's `domain` |
| `empty` | guidance is blank |
| `too_large` | guidance over 2000 characters (the Decision answer cap), or the new SKILL.md would exceed 256 KiB, the registry's file cap (it would make the skill unloadable) |
| `secret_in_content` | secret-looking text (the patterns of `scripts/secret_scan.py`, after NFKC normalisation) in guidance or answer. Either refuse (this reason) or redact; the tests pin only that the secret appears in nothing stored or returned, and that a refusal stores nothing |
| invalid text (lone surrogate) | `SkillProposalError` too, never `UnicodeEncodeError`, nothing written |
| `self_review` | `reviewer` is the proposer (or the answering Lead) |
| `not_expert` | `reviewer` is empty or not in `experts` |
| `already_decided` | the proposal is not `proposed` any more |
| `stale` | the skill's files changed since `base_sha256`; nothing is written |
| `too_many_open` | the proposer already has 20 open (`proposed`) proposals; 409 at the API |
| `invalid_text` | surrogate, control or line-separator character, or an invisible Default_Ignorable character (CGJ, variation selectors, Hangul fillers, tag characters, ...) other than one VS15/VS16 and one joiner right after a visible character; also checked on `reason` |
| `unsupported_skill` | skill.yaml has no single top-level `version:`/`reviewer:` line or a non-plain-semver version, so code cannot edit it safely |
| `unknown_proposal` | no such id |

Approve writes `skills/<domain>/<id>/SKILL.md` (= `proposed_body`, UTF-8, LF) and `skill.yaml` (`version` = `to_version`,
`reviewer` = the approving user id; every other field unchanged and still valid against `contracts/skill.schema.json`).
The answer text can only ever land in SKILL.md; it never changes skill.yaml fields, never creates a file. Reject, a
failed approve and `propose` change no file at all. A run still loads skills only through its pins (FR-AGT-03).

## API: `tilo_api.skill_proposals`

```python
def build_router(proposals: SkillProposals | Callable[..., SkillProposals], *, owner_of: Callable[[str], str | None]) -> APIRouter
def get_decision_store() -> DecisionStore   # dependency; DecisionStore.get(decision_id: str) -> dict | None
```

Mounted in `tilo_api.app` (`tilo_api/__init__.py`). The caller is `deps.get_current_principal` (declared first, so no
sign-in is 401 before anything else) and the Team Lead records are `tilo_api.console.get_team_leads`, read on every
request. A record counts only as in the console (`team_lead.schema.json`-valid, `assigned_by.by` is the world's owner
via `owner_of`, `assigned_by.at` not in the future). A principal whose `world_id` is not the path world gets 404.

| route | who | result |
| --- | --- | --- |
| `POST /worlds/{w}/skill-proposals` body `{decision_id, skill_id, guidance?}` (`extra=forbid`: 422) | role `team_lead` with a current record, the Decision's answerer | 201 `{"proposal": {...}}`; 404 unknown/other-world decision or unknown skill; 403 anyone else; other refusals 4xx `{"error": reason}`; nothing stored on any refusal |
| `GET /worlds/{w}/skill-proposals` | a current Team Lead: the proposals of their domain(s), plus their own | 200 `{"proposals": [...]}`; Viewer/Approver 403 |
| `GET /worlds/{w}/skill-proposals/{id}` | same scope | 200 `{"proposal": {...}}`; outside it 404 (no existence oracle) |
| `POST .../{id}/approve` body `{}` (`extra=forbid`) | role `team_lead`, a current record of the skill's domain, not the proposer | 200 `{"proposal": {...}}`; 403 (404 for a domain they cannot see) anyone else, including the owner as such, a Viewer, an Approver, the proposer, a removed or not-owner-assigned Team Lead; 4xx `{"error": reason}` for `already_decided`/`stale` |
| `POST .../{id}/reject` body `{reason?}` | same as approve | 200; skill unchanged |

A proposal belongs to the world of its Decision (`provenance.world_id`): list, get, approve and reject treat another world's proposal as absent (404 / omitted), whatever the domain slug.

The `skill.yaml` section of the diff shows `reviewer` as `<the approving expert, filled in by code>`; approval writes the approver's user id.

Identity is the verified principal only: no body field names a proposer, reviewer, status or role.

## Resolved ambiguities (PRD defaults; also for docs/open-questions.md)

1. "Expert role" (PRD 8.2 "the domain expert's approval", skill.yaml `reviewer`): no such row in PRD 10.1. Default: a
   Team Lead of the skill's domain (PRD 8.3), never the proposer, never the owner as such.
2. Who drafts the change: deterministic code appends the Team Lead's text under a heading; no model (PRD 16.1).
3. Who may promote: the Team Lead who gave the answer (PRD 10.5: the action is in their console). Whether the owner may
   promote is left open; not asserted.
4. Storage of proposals: in memory behind the class, like `CardStore`; a durable store is a later ticket.
5. Events: the acceptance criterion needs none; the tests assert none. If the builder wants a Trace event
   (`skill.change_proposed` / `skill.change_approved`), that needs a contract change first (registry entry, data
   schema, fixture); stop and report "needs contract change".
