# FR-HIL-10 Team Lead console: the API these tests pin

PRD 10.5, 10.6, 16.2, 8.3; ADR-0006. Acceptance: "A routed question appears in <= 2 s; answering resumes the agent
in <= 2 s." The web screen is an AG-WEB ticket; this file is the API and event half.

## `tilo_api.cards.CardStore.submit(..., domain=None)`

`domain` is the Team Lead domain the question was routed to (the `question.routed` `data.domain`), a
`common.schema.json` slug, or `None` for the owner fallback. Allowed only on a `needs_you` or `meeting` card; a
gate, a consent card or a non-slug (also over 64 characters) is `rejected`. The harness supplies it, never a
model. **The domain is part of the merge key** (with building, district and assignee), so merging never hides one
domain's question behind another's.

## `tilo_api.console`

```python
def get_team_leads() -> list[dict]      # FastAPI dependency: config/teams.yaml, team_lead.schema.json records
def build_router(cards: CardStore | Callable[..., CardStore]) -> APIRouter    # like cards.build_router
```

The console resolves the caller from `deps.get_current_principal` plus `get_team_leads()`: role `team_lead`, and a
record whose `user` is the principal's `user_id`; the record's `domain` is the console's domain. Districts do not
matter here. Anyone else (Viewer, Approver, unknown role, a Team Lead with no record, which is how a removed one
looks) is 403; a principal of another world is 404.

| Route | Success | Errors |
| --- | --- | --- |
| `GET /worlds/{world_id}/console` | 200 `{team_lead, domain, queue, history, stats}` | 403, 404 |
| `POST /worlds/{world_id}/console/cards/{card_id}/answer` `{option}` | 200 `{"outcome": "answered"}` | 400 `{outcome: rejected, reason: invalid_option \| already_resolved}`, 403, 404 `card_not_found`, 422 (extra field, wrong type), 503 `event_write_failed` |

- `queue`: card objects (card schema), open `needs_you` and `meeting` cards routed to the domain, oldest first, one
  per merged group. Cards routed to another domain, to the owner (`domain` null), and gates or consents are never
  in it, never answerable (404 `card_not_found`, nothing written).
- Answering writes one `question.answered` part, `data {answered_by: "team_lead"}`, with the card's world, district
  and `vis`, before the call returns; the card leaves the queue.
- `history`: this Team Lead's own answers (not a timeout default and not another Team Lead's), each `{card_id,
  option, answered_at, answer_time_s}`; `answer_time_s = answered_at - card.created_at` read from the store's
  injected `Clock`. `stats`: `{answered: n, median_answer_s: median | null}`.
- Timing: no tick, poll or timer is on either path; the tests assert 2.0 s in-process with a 0.5 s event writer.
