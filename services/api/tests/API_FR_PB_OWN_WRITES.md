# FR-PB-01/02/05/06 caller-owned writes

`POST /v1/pinboards` takes `title`, optional `body`, `kind` (default `note`),
`url`, and `team`. Omit `team` for the caller's private board. A named team
requires current membership. IDs, organisation, maker and setter are server-owned;
responsible person and due date start null. Optional Idempotency-Key follows the people API.

`POST /v1/pinboards/{pin_id}/delete` takes `{}`. The personal-board owner or
current team member who set up the pin can remove it. Removal preserves the record,
adds history and excludes it from the ordinary list; Tilo-made personal pins record `undone`.
Others get the same 404 as an unknown pin. A missing source owner also refuses a Tilo-made pin.

Both writes require existing pinboard events in the caller's private Desk.
CAS conflicts are 409; event failure rolls back content and returns 503.
The existing JSON/body limits, write limiter, declaration gate and no-store answers apply.

Move is unavailable: scope is immutable in the existing write validator, and
the closed pin schema has no board position/group/order fields. No contract changes here.
