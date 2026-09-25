---
name: redaction-and-kill-switch
description: ST-3a (FR-HIL-07 kill switches, FR-HIL-09/SEC-07 redaction in services/api) review history and the side channels that keep leaking hidden counts; check on any view/redaction, harness writer or kill-switch ticket
metadata:
  type: project
---

ST-3a review history (2026-09-25):
- Round 1 FAIL: no world membership on reads; fake run_id/self-computed seq; Stop all half-applied with a 500 (KeyError on policy_worlds); pause channel unvalidated; seq gaps leaked hidden counts; policy.changed always vis "all"; 404/403 oracle.
- Round 2 (9753f6c) FAIL: those closed (EventWriter part-only, Principal.world_id, validate-first, dense view seq, cause nulled, vis from scope.districts). Still leaking in GET /worlds/{w}/events (routes.py get_world_events copies everything but seq/cause): `trace.archive_ref` and `channel.message_*.data.message_ref` are `<run>/<archive record seq>`, a per-run counter over all model/tool/message records, so gaps count hidden work; `policy.applied.data.instruction_id` names a hidden event id (same class as cause). Test double ids `ulid(seq)` and the stream fixture ids encode seq too.
- Round 2 also: writer.append raising mid Stop all -> 500, earlier policies L1, later still L3, and the one being written is L1 with no policy.changed; a retry counts it already_l1 so its event is never emitted. policy.changed vis copies scope.districts even when those districts are not in the target world's layout (EV-13).

**Why:** SEC-07 acceptance is "scoped users never receive hidden names or counts"; PRD 10.1 "fog with no names or counts". Each round the builder fixes the named field (seq, cause) and leaves another field with the same meaning (archive_ref, instruction_id, real id). Same pattern as [[t3-invariant-gaps]].

**How to apply:** For any scoped view, enumerate every field of event.schema.json and every events/data/*.schema.json field that is a ulid, archive_ref or district_id, and ask whether it counts or names hidden things. Probe with scratchpad probe_st3a_r2.py (viewer D1, hidden D2 events carrying archive_ref, FlakyWriter raising on 2nd append).
