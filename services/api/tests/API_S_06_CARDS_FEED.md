# API-CARDS-FEED: `GET /cards` (S-06 needs-you queue; FR-HIL-01, FR-HIL-02, FR-HIL-11)

Tests: `test_S_06_cards_feed.py`. Open questions: BQ-S06-1..8 (docs/open-questions.md); the need is BQ-WIRE1-4. No contract
change needed: an item wraps the card exactly as `GET /worlds/{id}/cards` already returns it, and the wrapper is API-only.

## Who and what
- Auth: `deps.get_current_principal`, exactly as `GET /worlds`, `GET /worlds/{id}/cards`. No sign-in: 401, the same body.
  The user comes only from the session; a `user_id`/`owner`/`world_id` query parameter or an `x-*` header changes nothing.
- Read-only: GET only (POST, PUT and DELETE on `/cards`, and an answer POST under it, are 404 or 405). Nothing is written to
  the store, the event writer, the pending queue or any `CardStore`; the read never calls `tick()` and never closes a card.
- Scope (BQ-S06-1), as `GET /worlds` (BQ-S14-1): role `owner` covers every world whose `WorldRecord.owner` is their
  `user_id`, whatever world their principal names; any other role covers only `Principal.world_id`, if the world exists.
  Another person's world never appears, even for an owner whose session names it.
- Visibility and redaction are the per-world route's, not re-implemented: for each in-scope world the feed reads
  `CardStore.list_for_world(world_id, principal=<the caller narrowed to that world>)` (the callee of
  `GET /worlds/{id}/cards`; `tilo_api.runs.get_card_store(world_id, store)` finds the store). So the owner sees every open
  card; a Team Lead only their districts' cards (a hidden district's cards and its count never leave the API, SEC-07), never a
  question routed to the console; an Approver only the cards assigned to them; a merged batch is one card (FR-HIL-02). A Viewer,
  a person with no world, an unknown world: `200` with an empty list, never 403 or 404 (no membership oracle).

## Response (BQ-S06-2, BQ-S06-6)
`200 {"cards": [item, ...], "count": int, "next_cursor": str | null}`; nothing open: `{"cards": [], "count": 0, "next_cursor": null}`.
No fixture or sample card, ever.

Item, exactly these keys:

| key | value |
| --- | --- |
| `world_id` | the card's world, equal to `card.world_id` |
| `card_id` | the card's id, equal to `card.id` |
| `card` | the card byte for byte as `GET /worlds/{world_id}/cards` returns it to the same person |

Answering: `POST /worlds/{world_id}/cards/{card_id}/answer`, unchanged (identity from the session, a gate opens only in a
signed-in web session, first answer wins). The feed has no answer route of its own. T3 gate cards are listed like the others;
reading never resolves one (no T3 without a person).

`count` is the number of open cards in the caller's whole queue after the visibility filter, on every page whatever `limit`
and `cursor` say. The shell's needs-you count is `GET /cards?limit=1` -> `count`.

## Open means (BQ-S06-5)
A card is open until the store marks it resolved: a person's answer on any channel (FR-HIL-11: gone on the very next read, 2 s or
less, no cache), or `tick()` applying a question's safe default after its deadline (FR-HIL-02). A question past its deadline but
not yet ticked is still listed, as on the per-world route. A gate or consent card is only held by a timeout, never resolved, so it
stays listed until a person answers.

## Order and pages (BQ-S06-3, BQ-S06-4)
- Order: oldest first by `card.created_at`, ties by `world_id` then `card_id`, ascending. Total, so deterministic.
- `limit`: default 20, minimum 1, maximum 100. `0`, negative, non-integer, empty or over 100: 422 `{"detail": ...}`.
- `cursor`: opaque (no world or card id in it), a keyset on the order, bound by a keyed MAC to the caller's user id. One the API
  did not mint, was tampered with, or was minted for another person (a member replaying the owner's included): 400
  `{"detail": ...}`, naming no one. The scope is applied on every page whatever the cursor says.
- `next_cursor` is null on the last page, including a page exactly full with nothing after it (no empty trailing page).
- A card answered between two pages causes no duplicate and no gap among the others.
- Walking every page with any limit returns the caller's open cards exactly once each, in order (property test).

## Errors (BQ-S06-8)
A bad `limit` or `cursor` is refused (422, 400) before any world is read. If one world's card store fails, the whole read is a
503 `{"detail": ...}` with a fixed message and no exception text: never a 200 that silently drops a card waiting for a person.

## Consistency (property tests)
For every caller (owner of two worlds, an owner whose session names one of them, another owner, a Team Lead, an Approver, a
Viewer), over random worlds, kinds (needs_you, T3 gate, consent, meeting), districts, assignees, answered and open cards: the
items equal the union, sorted in the order above, of what `GET /worlds/{id}/cards` returns the same person for each in-scope
world; `count` equals its length on every page; no duplicate; no card of another user; a foreign cursor is always a 400; and a
read closes and writes nothing.

## Defaults chosen where the PRD is silent
Response keys `cards`/`count`/`next_cursor` and the wrapper item; oldest first with the id tie-break; default page 20, maximum 100;
422 for a bad limit and 400 for a bad cursor (stricter than S-14, as the ticket fixes it); a Viewer or an outsider gets an empty
list; `count` on the same route; 503 for a failing world rather than a partial feed.
