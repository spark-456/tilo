# ADR-0038: Owner-only pin placement without scope transfer

- Status: **Accepted by the user, 12 Oct 2026.** The contract lane's choices are the numbered decisions
  below. They are additive (`pinboard_item.schema.json` 1.1.0) and the user may override any of them.
- Decider: user; author: CX-MERGE, 12 October 2026.
- Requirements: FR-PB-01..07; supervisor ruling, 12 October 07:00 IST.

Acceptance note (issue #893): pinboard titles are typed only by the person; content inside remains editable.
Do not implement that note until the user confirms the reading.

## Context

`contracts/pinboard_item.schema.json` has no placement fields and rejects extra
properties. `tilo_people.writes._MAY` permits pin content edits but no placement
or scope edit. Create and delete already have owner-scoped routes; a move cannot
be represented by changing scope or deleting and recreating the pin.

## Proposal

Add an optional `placement` object to the pin contract:

```text
placement?: { board: string, column: string, order: integer }
```

Board and column identify presentation locations inside the pin's existing
scope, not a user, team, or access grant. Order is a non-negative integer;
ties use the stable pin ID. Bounded identifiers, board/column combinations and
limits are decisions 2 and 3 below.
Omitted placement preserves the current list presentation for existing records.

Placement writes are owner-only: for personal pins `scope.user` must equal the
authenticated caller; for team pins `set_up_by` must equal the caller and the
existing membership/source checks still apply. Team visibility alone grants
no write permission. The server derives caller identity and validates the
destination in the unchanged scope on every request.

A move changes placement only. Pin ID, `scope`, `org_id`, `set_up_by`, source,
confirmation, content, and access rights remain unchanged. Cross-person,
cross-team, and personal-to-team transfers are refused. No delete/recreate
substitute and no new event type are authorized by this proposal.

## Consequences and acceptance work

Before wiring a route or UI, tests must cover owner success, another person's
refusal, read-only team membership, destination validation, deterministic order,
old records without placement, unchanged scope/identity/source, and retention
of the recorded list after failed writes. The decisions below settle the points the
proposal left to the contract lane.

## Decisions (contract lane, 12 Oct 2026)

The contract: `contracts/pinboard_item.schema.json` 1.1.0 (additive minor) gains the
optional `placement` and `$defs` `placement` and `place_id`; the proposed rule PE-36 is in
`contracts/people.rules.md`. No event type, registry entry, config key or other frozen
schema changes. Generated names: `PinboardItemPlacement`, `PinboardItemPlaceId`.

1. **Shape as proposed.** `placement?: {board, column, order}`, closed, all three required
   when present. Left out until a pin is placed, never null (ADR-0011), so every old record
   stays valid and keeps the list presentation. It cannot be removed again once set; a
   reset is a move to a default column.
2. **Bounded identifiers.** `board` and `column` match `^[a-z][a-z0-9_]{0,31}$`; `order` is
   an integer from 0 to 9999. There is no catalogue of boards and columns, so any pair of
   ids is allowed: they are presentation inside the pin's own scope and never a grant, and
   the object has no field that could name a scope, a user or a team.
3. **Ordering.** `order` is a sort key inside one board and column across the entries of the
   scope, lowest first, ties by pin id ascending. A move writes the one pin and never
   renumbers another, which may belong to someone else.
4. **Owner-only move (PE-36, proposed).** A new request action `place` changes `placement`
   and nothing else: not the title, content, scope, `owner`, `status`, `set_up_by`, source,
   confirmation, `history` or `updated_at`. Personal: `scope.user` is the caller. Team: the
   `set_up_by` person who is also a member at the request, and the entry is `active`. A
   member, the responsible person (`owner`), a tagged person, an org owner or a Team Lead
   gets none. A move writes no event, and the title stays the person's own.
5. **Concurrency.** The people store's compare-and-set on the record version already
   serialises two moves; nothing new is needed.
6. **Code that must change, outside this lane.** `tilo_people.writes` (`_WRITES`, `_MAY`
   and a history rule for `place`) and `tilo_people.access.decide` (the `place` action). PE-36
   is a proposed row until then, and its crossref cases
   (`contracts/fixtures/pinboard_item/crossref/`) are not yet run by tilo-api.
7. **Issue #893.** Only the guard is here: a placement write never changes `title`. "Titles
   typed only by the person, content inside editable" is not implemented and waits for the
   user's reading, as the acceptance note says.

Questions logged: BQ-PLACE-1 to BQ-PLACE-3 in `docs/open-questions.md`.

## What builders do next

- Slice 1: `place` in `tilo_people.access` and `tilo_people.writes` (PE-36), tests first from
  the crossref files and `_refusal` in `tests/contracts/test_FR_PB_pin_placement_contract.py`.
- Slice 2: a tilo-api placement route and store write over that check, then the Pinboard
  UI's move on the live data. Create and delete are unchanged.
