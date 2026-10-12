# ADR-0038: Owner-only pin placement without scope transfer

- Status: Accepted (user, 12 Oct 2026); builders start after the architect's contract PR merges.
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
ties use the stable pin ID. The contract lane must define bounded identifiers,
allowed board/column combinations, and limits before this schema is accepted.
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

The contract lane must add the optional field, valid/invalid fixtures and
generated types, then approve a narrow placement-write operation/store allowlist.
Before wiring a route or UI, tests must cover owner success, another person's
refusal, read-only team membership, destination validation, deterministic order,
old records without placement, unchanged scope/identity/source, and retention
of the recorded list after failed writes. Concurrency and any audit/event schema
needed for that operation must be resolved by the contract lane first.

This draft changes documentation only. Move stays unavailable pending acceptance;
the deployed create/delete behavior continues on existing contracts.
