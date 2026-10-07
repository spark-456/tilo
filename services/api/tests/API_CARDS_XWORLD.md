# API-CARDS-XWORLD: an owner answers cards across the worlds they own (S-06; FR-HIL-01, FR-HIL-04, FR-HIL-11, SEC-06, SEC-07, SEC-11)

Tests: `test_S_06_xworld_answer.py` (every name contains `S_06_xworld`). Issue #539. Open questions: BQ-XWORLD-1..8
(docs/open-questions.md). No contract change: the events written are byte for byte those of a bound answer, and the audit
of the session's world is an application log record, not an event (BQ-XWORLD-4, BQ-XWORLD-5).

## Today
`GET /cards` (S-06) lists an owner's open cards across every owned world, but `POST /worlds/{world_id}/cards/{card_id}/answer`
and `GET /worlds/{world_id}/cards` are a 404 unless `Principal.world_id == world_id`, so a card from another owned world can
be seen in the feed and not answered.

## Who may answer cross-world (BQ-XWORLD-1, BQ-XWORLD-2)
"Cross-world" means the path's `world_id` is not the world the principal names (another world, or none).
- Role `owner`, and the card's world's `WorldRecord.owner` is the principal's `user_id`, and the run's `CardStore` owner check
  agrees (its own owner for that world is the same user). Checked per card, on every request; one answer opens no other world.
  If the two owners disagree, or either is someone else, or the world does not exist: the same 404 (status and body) the same
  principal gets for a world id that does not exist. A real card and no card in another person's world look the same.
- Only the user's own signed-in web or mobile_web session: `Principal.channel` is `web` or `mobile_web` and the request is
  not a tilo-channels caller. An email session (`channel == "email"`, or any tilo-channels caller, which is how signed email
  links act) answers only in the world its principal names. Share links (FR-HIL-12) are Approver principals on `/share/...`
  and stay bound. An ineligible session is refused with the unknown-world 404 before any channel check runs.
- An owner web session that names no world (`world_id` None) may answer in an owned world too: the feed shows it those cards.
- Approver, Team Lead and Viewer keep today's binding: any other world is the unknown-world 404, for answers and reads.
- A session bound to the card's world is unchanged (no new check).

## What a cross-world answer does (BQ-XWORLD-3, BQ-XWORLD-4)
Exactly what the same answer from a session bound to the card's world does: the same status and body, the same parts handed to
the card's world's writer (type, data, `authz` `{by: person, ref: user_id, at}`, `event_id`, scope), the same open/closed
state, nothing written to the session's world. Every existing check applies unchanged, in the same order, with the same
status and body: Pause all of the card's world (409; the session world's pause does not matter, BQ-XWORLD-8), a body
claiming `pin_verified` or a non-web channel (403 `channel_not_permitted`; no PIN path exists, ADR-0019), `session_allows`
(400 `invalid_channel`), and the store's `card_not_found`, `forbidden`, `already_resolved`, `busy`, `invalid_option` and
`invalid_channel`. An unknown card in an owned world is what the bound session gets.

## No auto-answer
Reading `GET /cards` or `GET /worlds/{id}/cards` never answers, never ticks and writes nothing, even past a T3 gate's deadline.
One answer resolves one card in one world: the same gate waiting in other worlds stays open. Every `authz` written names the
person who answered (FR-HIL-04 property test).

## Audit (BQ-XWORLD-5)
Every answered cross-world request (gate `edit`/`hold` and consent `hold` included, which write no event) leaves at least one
log record at INFO or above on a `tilo_api.*` logger whose message names the actor's `user_id`, the session's world (when
there is one), the target world, the card id and the option. Ids only: no bearer token, cookie, header value or card text in
any log record.

## Per-world reads (BQ-XWORLD-6)
`GET /worlds/{world_id}/cards` opens cross-world for an owner of that world exactly as `GET /cards` shows it (role owner and
record owner; the run's `CardStore.list_for_world` still decides what is shown), whatever channel the principal names (the
feed has no channel rule). The result equals the bound session's and the feed's items for that world. Another person's world
is the unknown-world 404. Non-owner roles stay bound.

## One scope (BQ-XWORLD-7)
For an owner, the worlds they can answer in = the worlds `GET /worlds` lists = the worlds `GET /cards` covers (BQ-S14-1,
BQ-S06-1). For anyone else, only the world their principal names. The S-06 feed and S-14 list tests are unchanged.
