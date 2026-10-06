# FR-HIL-12 Approver role and share links: the API these tests pin

PRD 10.1 ("Approver: assigned cards, assigned gates"), 10.3 ("gates need sign-in"), 16.2, SEC-06, SEC-08; BQ-32;
ADR-0006 (sharing a gate with an Approver after it is raised re-raises it as a new proposal with a new card; only the
owner creates the assignment, and the API takes `assigned_by` from the signed-in owner, never from the body).
Acceptance: "An Approver answers a gate from a shared link after sign-in." The tests are
`test_FR_HIL_12_approver_share_links.py`; no UI. The PRD fixes the behaviour, not the routes: the routes and field
names below are this ticket's defaults, so a builder may rename them only by changing the tests with the architect.

## `tilo_api.sharing`

```python
def build_router(cards: CardStore) -> APIRouter      # same store the cards router uses; keeps its own link records
```

| Route | Who | Success | Refusals |
| --- | --- | --- | --- |
| `POST /worlds/{world_id}/cards/{card_id}/share` `{approver: <user id>}` | the world's owner, signed in | 201 `{share_id, token, card_id, expires_at}` | 401 unsigned; 404 or 403 anyone else (Team Lead, Approver, Viewer, other world); 400, 404 or 409 a resolved, unknown or non-gate card; 422 any other body field (`assigned_by`, `by`, `authz`, `outbox_id`) or a bad user id |
| `GET /share/{token}` | the named Approver, signed in | 200 `{card}` (the re-raised gate card) | 401 unsigned (before any token lookup); 404 any other user or an unknown token, with the same body for both; 404 or 410 expired or revoked |
| `POST /share/{token}/answer` `{option}` | the named Approver, signed in | 200 `{"outcome": "answered"}`; edit and hold write nothing | as above; 400 `already_resolved` on a second answer; 400 an option the card does not offer; 403 or 422 any identity, channel, `pin_verified` or `authz` field in the body |
| `DELETE /worlds/{world_id}/shares/{share_id}` | the world's owner | 204 | 401 unsigned; 403 or 404 anyone else |

### Behaviour

- **Sharing is a new proposal.** It submits a new gate card (new id, same gate id, tier, irreversibility, recipients and
  pinned item, CR-12) with a fresh `outbox_id`, and writes one `approval.requested` part (`authz` null) whose `data`
  validates against `contracts/events/data/approval.requested.schema.json` and names
  `approver = {user, assigned_by: {by: <the signed-in owner>, at: <API clock now>}}`, `team_lead` null. The original
  card is untouched and still not answerable by the Approver.
- **Who counts.** The named user, signed in as role `approver` in the link's world, and only before `expires_at` and
  before revocation. The link opens one gate. A Team Lead, another Approver, a Viewer or the owner naming
  themselves opens nothing.
- **The answer.** Written through the cards store: `approval.resolved` with `channel` `web`, `pin_verified` false,
  `authz` `{by: person, ref: <approver>, at: <API clock now>}`. It is refused (nothing written) when that `at` is
  earlier than the assignment's `assigned_by.at` (BQ-32). `tilo_policy.open_gate` then decides; the API never
  decides authorisation and never writes an outbox entry.
- **Secrecy.** The token appears in no event and no stored card. Refusals carry only a stable reason.

## Defaults chosen where the PRD is silent (listed in the test-writer report)

1. Routes, field names and status codes above (the PRD names none).
2. The lifetime of a share link is the server's, returned as `expires_at`; the tests do not assert a number of hours
   (PRD 10.3's 24 h is for email question links only).
3. Only a gate card can be shared (FR-HIL-12 says "answers a gate"); an Approver's access to assigned questions
   (PRD 10.1 "Assigned cards") is not changed by this ticket.
4. Revoking a link ends the Approver's assignment but does not close the gate; the owner can still answer it.
5. Whether the original gate card is withdrawn after a re-raise is not tested.
