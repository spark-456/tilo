# Bot-hosted meeting, the tilo-api half: what these tests pin (FR-MTG-09, ticket MTG09-b)

Spec: `services/connectors/tests/API_FR_MTG_09.md` ("Ordered flow" steps 1 to 9, "Hostile cases", "Builder notes and
ticket split"), ADR-0024, `docs/prd-supplement-note-mtg09-2026-10-06.md`. The connector half (`tilo_connectors.
meeting_host`, `adapters/meeting_host.py`, grant groups, config) is MTG09-a and exists. The S-26 button is a later ticket.
Nothing here changes `contracts/`; see "Needs contract change" at the end.

Test files (all `services/api/tests`, helpers in `_mtg09b_lib.py`): `test_FR_MTG_09_host_route.py` (statuses),
`test_FR_MTG_09_host_gate.py` (the flow), `test_FR_MTG_09_host_generic_path.py` (the Opus security requirement),
`test_FR_MTG_09_host_abandon_and_conference.py` (disconnect, `conference: failure`).

## The route

`POST /v1/meetings/{meeting_id}/host`, body `{}` (the same `json_body(Empty)` the other owner actions use: any other body is
422 before any lookup). Behind the SEC-15 gate like every people route; every answer, refusals included, is
`Cache-Control: no-store`; the principal is `deps.Principal.user_id` (the session's world role neither grants nor takes
away); the org is `deps.ORG_ID`; the clock is `deps.get_clock` (never the wall clock).

| Answer | When |
| --- | --- |
| 200 `{"world_id": <the meeting's world>, ...}` | the owner asked, the draft is valid, the host run exists and its gate card is (or is about to be) posted |
| 404 (one body) | not the meeting's owner, unknown or other-org meeting, malformed id, a deleted (tombstoned) meeting (PE-05) |
| 409 | the meeting is not `scheduled`, or its `source` is not `bot` (status `live`, `ended`, `discarded`; source `upload`), or a host run for it already exists (waiting at its gate, or sent); two simultaneous requests make one 200 and one 409 |
| 422 `{"detail": <short text>, "rule": "MH-0n"}` | the connector refuses the draft: `MeetingHostRefused.rule` (MH-01 a record that breaks the meeting schema such as the title pattern, MH-02 window, MH-03 recipients, MH-04 time zone, MH-06 card sentence); the text names the rule and ids only, never a title, address, time or token |
| 503 `{"detail": "not_configured"}` | an unwired seam (below), or a store that cannot be read; nothing is started |

The draft is `draft_meeting_event(meeting=<stored record>, persons=<owner + attendee users' records>, actor=<principal>,
now=get_clock(), config=load_meeting_host_config(...))`: nothing from the request reaches it.

## Seams (all FastAPI dependencies, overridden in tests like the CL-INT-2 run seams)

Existing, used as they are: `get_people_stores`, `get_artifact_store`, `get_redactor`, `get_clock`, `get_store`,
`get_event_writer`, `get_outbox_store`, `get_connector_registry`, `get_run_archive`, `get_current_principal`.
`get_connector_adapters` is NOT where the host adapter comes from (decision below).

New, and unwired by default (the production default raises `HTTPException(503, "not_configured")`, EFF-01: no live
transport in dev):

- `deps.get_token_broker()`: an object with `access_token_for_adapter(user_id, connector, *, required_scopes,
  force_refresh=False) -> str` (and, optionally, `connection_state(user_id, connector)`), the `TokenBroker`'s adapter-facing
  half. Tests pass a fake that raises `tilo_connectors.tokens.NotConnected` while disconnected.
- `deps.get_meeting_host_transport()`: a `Transport` (`request(method, url, *, params, headers, json, content)`) for
  `MeetingHostAdapter`. Tests pass `FakeHostCalendar`.

**Decision (design B):** the host route builds the `MeetingHostAdapter` itself, per run, from those two seams plus its
own run-bound pieces: `owner_of` from `Store.worlds`, an `ArtifactSource` over the artifact store in the run's Scope, a
`ReceiptStore` over the artifact store in that Scope (origin `unit`, so the receipt is a real artifact whose ref the run
knows), `clock=events.now`, `sleep` a no-op. The run's outbox uses `{"meeting_host": that adapter}`. Reason: only the API
knows the receipt's ref, which step 9 needs (`artifact.created`, manifest, `sent` revision); a composition root cannot
hand it over through `execute_side_effect`'s return value, which the outbox ignores.

## The host run (steps 3 to 9)

- The meeting's world is `meeting["world_id"]` (PE-22; the world's owner is the meeting owner, PE-12) and its
  `Store.worlds[world_id]` record gives the run id. A meeting without a world is not covered here (ticket PPL-11c slice 6
  makes the world; the tests only use meetings that have one).
- A fixed plan, no Director, no worker model, no must-ask question: one unit `U1` (a `deliver`-style unit that holds the
  draft), one gate (T3, action `create_meeting_event`, connector `meeting_host`), validated by `validate_plan` and laid
  out by the layout builder seam like any plan. `plan_compiler` and `unit_runner` are never called.
- `U1` stores `draft.content` (`application/json`, origin `unit`, key `<run_id>:U1:<attempt>:0`, AR-05) through the artifact
  store and the run announces it (`artifact.created`) before the gate.
- `Run.gate()` seams: the recipients, destination and known recipients are `{recipients: draft.recipients, destination:
  "primary", known_recipients: []}` (the resolver, step 5 of the gate), never the generic address-book resolver (the tests
  install one that answers a stranger); `gate.action.exact` is `draft.exact` for this action instead of `_exact`; the card
  is the generic gate card otherwise (`answer_channels` `["web", "mobile_web"]`, T3, irreversible, `safe_default` hold).
- `approval.requested`: `item` the draft ref, `risk_tier` T3, `irreversible` true, `approver` and `team_lead` null.
- Only an approving `approval.resolved` from the owner's signed-in web or mobile web session enqueues the entry
  (`host_gate(...)` fields, the approval's `authz`); a policy never opens it (T3 allows at most L1); email, another person,
  a viewer or an approver does not.
- After the send: one `data.transfer` out (authz = the approval's, `data.artifact` = the draft item, no recipients); an
  `artifact.created` for the receipt (JSON, the pinned bytes, no link, address, title or time; with `content_sha256`,
  `media_type` and `size_bytes` copied from its stored record, artifact.created 1.1.0); the receipt's manifest
  `inputs` is `[draft ref]`; the draft's manifest has a `sent` revision whose `cause` is the `data.transfer` id and whose
  `authz` equals the transfer's (AR-06, MF-04).
- `conference: failure` (read back through the receipt): one `needs_you` card whose `what_happened` contains "Google did
  not add a Meet link", ids only; the entry stays `sent`. `success` and `pending` raise none.

## The disconnect handler

`tilo_api.meeting_host.on_connection_event(part: Mapping, *, outbox_store) -> int`: the sink the token broker's `emit` is
wired to (parts have `TokenBroker._emit_part`'s shape `{"type", "authz": None, "data": {"connector"}, "user_id"}`).
For `type == "connection.revoked"` and `data.connector == "meeting_host"` it abandons (`Outbox.abandon`) every entry of
connector `meeting_host` in state `queued`, `scheduled` or `sending` whose `authz.ref` is `part["user_id"]` and returns
how many it abandoned. Any other type, connector or user, and any malformed part, abandons nothing and returns 0 (never
raises). An entry whose lease is live may refuse the abandon: the handler is called again on the next event.

## The generic planned-unit path

`create_meeting_event` stays off the generic planned-unit gate path (the plan or the gate refuses a planned unit that
names it), or the adapter re-validates the draft (MH-02, MH-03, the meeting title pattern). The test registers the real
adapter in a generic run and asserts the run ends failed with no request to the calendar for a three-hour window, an end
before the start, a link in the title and a recipient who is no person of the org. MH-03 cannot be checked inside the
adapter (it has no person records), so keeping the action off the generic path is the simple way to pass all four.

## Defaults chosen where the spec is silent (also in `docs/open-questions.md`, BQ-MTG09-20 to -24)

no must-ask question before the gate (a T3 action in a generic plan always asks "go ahead?" first; the owner's own
request to host replaces that question, the gate card is the one authorisation); 200 with `{"world_id": ...}` for the route; 409 while a host run is pending as well as after it sent (a held or edited
gate ends that run; asking again after a hold is not pinned); 409 (not 422) for status or source; a deleted meeting is
404, a discarded one 409; the disconnect handler's signature above.

## Needs contract change

None for these tests. No new event type is needed: `approval.requested`, `approval.resolved`, `data.transfer`,
`artifact.created` (and `world.*`) are registered and fixtured. Open question for the architect, not asserted anywhere:
whether a meeting world's stream may carry these events with no `budget.granted` / `world.started` before them
(event.rules.md EV rules). The tests validate each event against its schema and the registry only, not the sequence rules.

**Superseded in part by ADR-0032 (T4):** `deps.get_token_broker` and `deps.get_meeting_host_transport` are gone; the host run's connector is `MeetingHostStub` over `deps.get_meeting_host_client` (tests: `InProcessConnectors` in `_mtg09b_lib.py`, `test_ADR32_T4_*`). The rest of this file holds.
