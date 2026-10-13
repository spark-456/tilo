# API-WORLDS-LIST: `GET /worlds` (S-14, FR-WLD-08)

Tests: `test_S_14_worlds_list.py`. Open questions: BQ-S14-1..5 (docs/open-questions.md). No contract change needed: every
field below is read from events and world records that already exist.

## Who and what
- Auth: `deps.get_current_principal`, exactly as `GET /worlds/{id}` and `/worlds/{id}/cards`. No sign-in: 401, the same body.
- Read-only: GET only (POST, PUT and DELETE on `/worlds` are 404 or 405); nothing is written to the store, the writer or the queue.
- Scope (BQ-S14-1): a principal with role `owner` sees every world whose `WorldRecord.owner` is their `user_id`, whatever world
  their principal names (the `GET /costs` precedent). Any other role sees only the one world `Principal.world_id` names, if
  it exists. No world, or an unknown one: an empty list, never a 404 (no membership oracle). Another person's world never appears.

## Response
`200 {"worlds": [item, ...], "next_cursor": str | null}`. Empty: `{"worlds": [], "next_cursor": null}`. No fixture world is ever listed, with one exception (STARTER-1, BQ-STARTER-1,
`tests/test_STARTER_1_sample_project.py`): the recorded sample project `w_sample_village_basic`, an item with `sample: true` and
title `Sample: <its world.requested title>`, listed for an owner with no worlds of their own or on `?include_sample=1`.

Item, exactly these keys (BQ-S14-2):

| key | value |
| --- | --- |
| `world_id` | the world's id |
| `title` | `data.title` of the world's first `world.requested` event; `null` with none |
| `status` | latest registered `world.*` event: `world.started`/`world.resumed` -> `started`, `world.paused` -> `paused`, `world.completed` -> `completed`, `world.failed` -> `failed`; none yet: `idle` (as the web's `worldStatus`). An unregistered type changes nothing (HR-5); the `WorldRecord.paused` flag alone says nothing (HR-1) |
| `created_at` | `ts` of that same first `world.requested`; `null` with none |
| `last_seq` | `seq` of the last recorded event (0 with none): where a replay of the finished run ends (FR-WLD-08) |

A member who is not the owner gets `last_seq` from their own view of the events, as `GET /worlds/{id}/events` numbers it
(hidden events dropped, the rest renumbered), so the list never reveals how many events they cannot see (BQ-S14-4).

## Order and pages (BQ-S14-3)
- Order: `created_at` descending (newest first); ties by `world_id` descending; worlds with `created_at` null last, by `world_id` descending. Total, so deterministic.
- `limit`: default 20, minimum 1, maximum 100. `0`, negative, non-integer, empty or over 100: 4xx (422 by default) `{"detail": ...}` (BQ-S14-5).
- `cursor`: opaque string from `next_cursor` (it does not spell out a world id), keyset style, so a world created between two pages causes no duplicate and no gap among the others. A cursor that is not one the API minted, or that was minted for another person: 4xx `{"detail": ...}` (400 by default), or at the very least none of another person's worlds (the tests accept either, never a leak).
- `next_cursor` is `null` on the last page, including a page that is exactly full with nothing after it (no empty trailing page).
- Walking every page with any limit returns the caller's worlds exactly once each, in the order above (property test).

## Defaults chosen where the PRD is silent
Default page size 20, maximum 100; error status for a bad limit 422 and a bad cursor 400 (the tests accept 400 or 422 for both); the wrapper keys `worlds` and `next_cursor`; the item key names (`world_id` as `GET /worlds/{id}` uses it); order newest first by `created_at` with the id as tie-break.

## Team worlds (TSW-4b, BQ-CTX-TEAMWORLD, BQ-TEAMWORLD-8)
`test_BQ_CTX_TEAMWORLD_TSW4b_worlds_list_access_team.py`. A full web or mobile-web sign-in bound to no world also lists the worlds it
reads as a team reader (a share in force, decided per request by `deps.team_reader`), in the same order and with the same cursor as above.
A team item has the same five keys as the reader's own view of the world gives, plus `"access": "team"`; the person's own items carry
no `access` key. Revoked, lapsed or left-team shares are gone on the next request; a people store that cannot be opened is the own list.
