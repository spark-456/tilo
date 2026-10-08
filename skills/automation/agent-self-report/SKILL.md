# Agent Self-Report (`agent-self-report`)

## When to use
Use this skill inside the **Meeting Hall / Meeting Room** (`ADR-0028`, `MR-06`, `MEETROOM_SELF_REPORT`) when a convener calls a Lead and its agents to the table and asks an agent unit what it did, why it made a choice, what work is left, or about a specific detail of the run.

## Steps
1. **Read only the unit's recorded events (`events`)**:
   - An agent in the meeting room is its record, not a live tool-calling process (`ADR-0028` Decision 1.2).
   - Inspect only the provided event slice (`seq`, `type`, `actor`, `target`, `summary`, and `data` such as `envelope`, `skill`, `artifact`, `gate_id`, `result`). Never infer actions from outside the slice.
2. **Answer in first person (`I`, `my`, `we`)**:
   - Structure the response around **what I did** (`what_i_did`), **why** (`why` — grounded in `agent.handoff` envelopes, acceptance criteria, upstream causes, or user rollbacks/approvals), and **what is left** (`what_is_left` — pending gates, unfinished buildings, or nothing left after completion/delivery).
3. **Cite event sequence numbers on every sentence and claim (`[seq: N]`)**:
   - Every sentence in `answer` and every entry in `what_i_did`, `why`, and `what_is_left` must include an inline `[seq: N]` (or `[seq: N, M]`) citation.
   - Every cited sequence number must exist in `events` (`MR-06`), and `cited_seqs` must match the exact set of inline sequence numbers.
4. **Honesty on absent facts (`"I have no record of that"`)**:
   - When asked about an action, tool, recipient, reason, or event that does not appear in `events`, set `has_record: false` and state `"I have no record of that"` in `answer`, citing the recorded events that define the actual scope of what was recorded.

## Quality bar
- **100% sentence-level citation coverage**: Every sentence in `answer` contains at least one `[seq: ...]` tag whose sequence numbers all exist in the input `events`.
- **Strict grounding (`MR-06`)**: Zero fabricated reasons, unrecorded tools, or external assumptions.
- **Explicit absent-fact refusal**: Unrecorded facts always trigger the exact phrase `"I have no record of that"` with `has_record: false`.

## Checklist
- [ ] Reply is written in first person (`I` / `my`).
- [ ] Every sentence in `answer` carries a `[seq: N]` citation.
- [ ] Every integer in `cited_seqs` and inline `[seq: ...]` exists in the input `events` slice.
- [ ] `"why"` questions are answered strictly from recorded handoff briefs, acceptance criteria, or upstream cause events.
- [ ] Questions about absent facts say `"I have no record of that"` and set `has_record: false`.

## Pitfalls
- **Inventing a plausible "why"**: Never guess why a draft or triage choice was made if no handoff envelope, decision, or event records the reason; say `"I have no record of that"`.
- **Leaving trailing summary sentences uncited**: Even concluding sentences ("Nothing is left for my unit [seq: 40].") must carry a valid `[seq: N]` citation.
- **Citing sequence numbers from other agents or districts**: Only cite `seq` values present in the addressed agent unit's `events` slice.
