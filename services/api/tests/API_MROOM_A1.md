# MROOM-A1: meeting room routes, slice 1 (what the acceptance tests pin)

Source: ADR-0028 decisions 1 to 5, 7, 9, 10, 13; `contracts/meeting_room.rules.md` MR-01 to MR-05, MR-06 (reply step), MR-08,
MR-11 (reply step), MR-12; skill `agent-self-report`. Tests: `test_MROOM_A1_room_routes.py`, `test_MROOM_A1_reply_step.py`,
`test_MROOM_A1_dev_mode.py`; rig `_mroom_a1_lib.py`. `POST .../changes` is MROOM-1b (`test_MROOM_1b_changes.py`, BQ-MROOM-1b-1). Not built: the revision planner (MR-H2).

## Routes (`tilo_api.meeting_room`, mounted at `/v1/worlds/{world_id}/rooms`)
- `POST` (convene_request): 201 the room (root shape); 403 `not_allowed` (Viewer, team Viewer, no team role, district outside
  the person's view, the Director's room for anyone but the owner) or `demo_session`; 409 `world_paused`, `room_open`,
  `no_layout`; 422 `bad_request`, `bad_attendees`; 503 `not_configured`.
- `GET /{room_id}`: the room; the words come from the archive. The world's owner or the convener; anyone else, a missing
  room and another world are one 404 body.
- `POST /{room_id}/turns` (ask_request): 202 with the finished turn (slice 1 computes the reply inside the request: `meeting.asked`,
  then `meeting.replied`). 403 `access_lost`; 409 `world_paused`, `room_closed` (+ `reason`), `turn_in_flight`; 422; 503.
- `POST /{room_id}/adjourn`: 200 the room (idempotent). Only the convener speaks or closes (the events name them as actor).

## Rules
- Events go through `deps.get_event_writer` only; `authz` null; the convener (or `system`) is the actor of room events and
  the replying agent of `meeting.replied` (MR-01). `vis`: every attendee's district, `all` for the Director's room.
- Attendees (MR-02) come from the world's layout; a worker's district is the district its recorded events carry.
- Access is re-checked at every request (MR-03): owner, or an Approver or Member from the team store (`config/meeting_room.yaml`
  `convene_roles`) whose `Principal.districts` cover every attendee's district. A convener who fails it later gets 403
  `access_lost` and the room adjourns (`access_lost`). Idle, paused and access are swept on access.
- Turns count from 1; one in flight (an in-process lock, and an unanswered `meeting.asked` in the events) (MR-04).
- Pause all and Stop all (`dispatch`) call `meeting_room.adjourn_open_rooms` first: `meeting.adjourned` (`paused`) is written
  before `world.paused` (MR-05).
- Credits (MR-08): the model's `quote(mode)` is reserved against the room's remaining cap before any call; a turn that
  would pass it, or pass `max_turns`, is refused and the room adjourns `capped`.
- Text (MR-12): the person's words and the replies are only in the redacted archive (`channel_in` / `channel_out` records of the
  discussed run), behind `message_ref`; the secret redactor runs first.

## Reply step (`tilo_api.meeting_room_reply`)
- Grounding is built by code from the world's recorded events for the addressed agent only: a worker's events (it is the actor
  or target), a Lead's district, the Director's all; plus the layout's `plan_units` for a Lead or the Director. `meeting.*`
  events are never grounding. Artifact versions come from `artifact.created|versioned`.
- The person's text is screened first (flagged: `declined`, no model call, never a proposal) and fenced with
  `tilo_harness.untrusted.neutralise`; a flagged recorded line is left out with a note.
- Roles `meeting_room` (quick) and `meeting_room_thinking` (`meeting` is the meet-bot's role, BQ-MROOM-A1-1).
- Reply JSON: `has_record`, `text` (1 to 4000), `units`, `artifacts`, `proposal` (units and artifacts only). One id outside the
  grounding set, a wrong shape, a proposal key beyond those two, or an answer citing no unit: `failed`, no text, nothing
  trimmed. `has_record: false`: `declined` with "I have no record of that.".
