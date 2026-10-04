# FR-CHN-08: public API pinned by the Gmail watch tests (overridable)

FR-CHN-08 "Gmail push watch with polling fallback". The acceptance test is "New mail is triaged in ≤ 60 s p95"
(PRD 11.6, NFR-08). Sources are PRD 6.3 (Pub/Sub carries Gmail push notifications; Cloud Tasks and Cloud
Scheduler run the autopilot polling fallback), 11.2, 11.3, 11.6, 12.1, 16.1 to 16.3, SEC-08 and NFR-22, plus
`services/channels/CLAUDE.md`. These Gmail API facts are not stated in the PRD: a watch expires after 7 days;
`history.list` answers 404 once `startHistoryId` is too old; a push carries only `{emailAddress, historyId}`.

These are the tests' assumptions, and the architect or builder may override them. If a name or shape below
changes, update the tests in the same PR and say so in the review. The tests import only what is listed here.
The test doubles are in `_chn08_lib.py` (channels) and `services/connectors/tests/_chn08_gapi_lib.py`.

## `tilo_channels.gmail_watch` (new module)

```python
WATCH_TTL_S = 7 * 86400        # Gmail's watch lifetime
RENEW_BEFORE_S: float          # 0 < RENEW_BEFORE_S < WATCH_TTL_S; renew_due() re-watches inside this window.
                               # The 30-day test sweeps hourly, so it must exceed 3600 (suggested 86400).
POLL_INTERVAL_S: float         # the cadence at which the sweeper (Cloud Tasks) calls poll_due() and renew_due().
                               # The latency test drives both at exactly this cadence (suggested 30).
RESYNC_MAX_MESSAGES: int       # 1..50 (gmail connector batch_size); suggested 50

class Mailbox(Protocol):       # GmailAdapter in production (connectors side below)
    def watch(self, user_id: str, *, topic_name: str, label_ids: Sequence[str]) -> dict
        # {"history_id": str (decimal), "expiration": float (unix seconds)}
    def stop_watch(self, user_id: str) -> None
    def list_history(self, user_id: str, start_history_id: str, *, page_token: str | None = None) -> dict
        # {"history_id": str, "message_ids": list[str] (INBOX messagesAdded, oldest first, may repeat),
        #  "next_page_token": str | None}; raises an exception with .status == 404 when the start id expired
    def recent_inbox(self, user_id: str, *, max_results: int) -> dict
        # {"history_id": str (read BEFORE listing), "message_ids": list[str] (newest first)}

class WatchStore(Protocol):    # Firestore in production; JSON-able dicts
    def get(self, user_id: str) -> dict | None
    def put(self, user_id: str, value: dict) -> None
    def delete(self, user_id: str) -> None
    def user_ids(self) -> list[str]

# DedupeStore is tilo_channels.whatsapp.DedupeStore: claim(key, ttl_s) -> bool (atomic set-if-absent).

class MailWatcher:
    def __init__(self, *, mailbox: Mailbox, store: WatchStore, dedupe: DedupeStore,
                 triage: Callable[[str, str], object],      # (user_id, message_id): FR-CHN-09 via tilo-api
                 clock: Callable[[], float], topic_name: str,
                 emit: Callable[[dict], None] = ...) -> None
    def start(self, user_id: str) -> None    # watch(label_ids=["INBOX"]); cursor = the returned history_id
    def stop(self, user_id: str) -> None     # stop_watch; later pushes, polls and renewals do nothing for the user
    def on_push(self, user_id: str, history_id: str) -> None
    def poll_due(self) -> None               # never raises for one user's failure; other users still polled
    def renew_due(self) -> None              # never lets one failure stop the sweep; a failed renewal is retried
```

The tests check this behaviour:
- `on_push` lists history from the stored cursor, never from the pushed id, and follows every page before it
  moves the cursor to the response's `history_id`. The cursor never moves back. Each message id is claimed
  in `dedupe` before `triage` runs, so it is triaged at most once, across restarts and across instances that
  share the stores. A user's mail is triaged in mailbox order and one call at a time (serialised per user).
- A renewal never replaces the cursor. Mail that arrives just before a renewal, with its push lost, is still
  triaged.
- `poll_due` skips a user whose history was read moments ago, by a push or a poll, and polls a user with no
  read for more than `POLL_INTERVAL_S`. The builder chooses the exact rule. When a user's pushes never arrive,
  the p95 latency must still be ≤ 60 s while `poll_due` runs every `POLL_INTERVAL_S`.
- A 404 from `list_history`, whether during a push or a poll, triggers exactly one `recent_inbox` call with
  `max_results ≤ RESYNC_MAX_MESSAGES`. Unseen ids are triaged oldest first, and ids triaged before are skipped.
  The cursor becomes the resync's `history_id`, so there is no second resync.
- A transient mailbox error (status 503) loses no mail, because the next poll recovers it within 60 s.
- The watcher never fetches message content, only ids. Reading content is triage's job, through the
  quarantined reader (PRD 16.3).
- Anything emitted is `{type, data, ...}`, with `type` in `contracts/events/registry.yaml` and `data` valid
  against its schema. No event is required.

## `GmailPushEndpoint`

```python
@dataclass(frozen=True)
class PushResponse:
    status: int
    body: str            # short and generic (≤ 64 chars): no token, claim, address, payload or exception text

class OidcVerifier(Protocol):    # google-auth id_token verification in production
    def verify(self, token: str, audience: str) -> Mapping[str, Any]   # checks signature + expiry; raises on failure

class GmailPushEndpoint:
    def __init__(self, *, verifier: OidcVerifier, audience: str, service_account: str,
                 accounts: Callable[[str], str | None],        # Gmail address -> user_id (watched accounts)
                 on_notification: Callable[[str, str], object], # (user_id, history_id as decimal str)
                 emit: Callable[[dict], None] = ...) -> None
    def receive(self, headers: Mapping[str, str], raw_body: bytes) -> PushResponse
```

The checks run in this order, and nothing runs after a failed one:
1. The `Authorization: Bearer <token>` header is read; the header name is case-insensitive. If it is missing,
   empty or uses another scheme, the answer is **401**.
2. `verifier.verify` raises: **401 or 403**.
3. The endpoint checks the claims itself: `aud == audience`, `iss` in {`https://accounts.google.com`,
   `accounts.google.com`}, `email == service_account`, and `email_verified is True` (a bool, not a string).
   Any other value gives **401 or 403**.
4. The body is parsed: Pub/Sub `message.data` is standard base64 of `{"emailAddress": str, "historyId": int or
   decimal str}`, with `historyId` from 0 to 2^64−1 and ASCII digits only. Any other shape gives **400**.
5. An address with no watched account is acknowledged with 2xx and ignored. Otherwise `on_notification` is
   called and the answer is 2xx. If `on_notification` raises, the answer is **≥ 500**, so Pub/Sub redelivers.

A refused push never calls `on_notification` and never emits. Logs never contain the token, the address, the
body, the base64 data or the verifier's or downstream exception text; they log exception types only.

## `GmailAdapter` (connectors side, `services/connectors/tests/test_FR_CHN_08_gmail_watch_adapter.py`)

These are new read methods on `tilo_connectors.adapters.GmailAdapter`, so the adapter satisfies `Mailbox`
directly. They use the `read` scopes only (gmail.readonly). They are not side effects: no outbox entry, no
grant, no event.
- `watch(user_id, *, topic_name, label_ids)` sends `POST users/me/watch` with `{topicName, labelIds, ...}`.
  `expiration` (epoch ms) is returned as unix seconds. A topic that is not `projects/<id>/topics/<name>`
  raises `AdapterError` before any request.
- `stop_watch(user_id)` sends `POST users/me/stop`.
- `list_history(user_id, start_history_id, *, page_token=None)` sends `GET users/me/history` with
  `startHistoryId`, `historyTypes=messageAdded`, `labelId=INBOX` and `pageToken`. A start id that is not ASCII
  digits raises `AdapterError` with no request. A 404 raises `AdapterError` with `.status == 404`, sent once
  with no retry and no sleep.
- `recent_inbox(user_id, *, max_results)` sends `GET users/me/profile` (for `historyId`) and then
  `GET users/me/messages` with `labelIds=["INBOX"]` and `maxResults ≤ batch_size` (50).

## Defaults chosen where the PRD is silent (proposed open-question rows; the merger allocates ids)

| ID | Question | Default taken in these tests | Source |
| --- | --- | --- | --- |
| BQ-TBD | Is mail already in the inbox when Email Autopilot starts "new mail"? | No. The cursor starts at the history id `watch()` returns, so only later mail is triaged. | PRD 11.6 FR-CHN-08 ("New mail") |
| BQ-TBD | Which labels are watched and triaged? | INBOX only (`labelIds=["INBOX"]`, `historyTypes=messageAdded`). The user's own sent mail, drafts and archived mail are not triaged. | PRD 11.2, 11.3 |
| BQ-TBD | What is the renewal window, and how often do the sweeper's poll and renewal run? | `RENEW_BEFORE_S` suggested 1 day (Google recommends a daily re-watch). `POLL_INTERVAL_S` suggested 30 s through Cloud Tasks, because Cloud Scheduler's 1-minute floor would leave no margin under 60 s p95. | PRD 6.3, NFR-08 |
| BQ-TBD | How far does a resync after an expired history id go? | One page of the newest INBOX mail, at most `RESYNC_MAX_MESSAGES` (50 = gmail `batch_size`), oldest first, skipping mail already triaged. Older unseen mail is not triaged. | PRD 6.6 (bounded work), config/connectors.yaml |
| BQ-TBD | How does the Pub/Sub push endpoint authenticate, and what does it answer? | An OIDC token from the push subscription's service account: aud = the endpoint URL, iss = Google, email and `email_verified` checked. 401/403 when unauthenticated, 400 when malformed, 2xx for an unknown address, 5xx when processing fails. | PRD 16.2, SEC-08 |
| BQ-TBD | Are `users.watch` and `users.stop` side effects that need the outbox (SEC-03)? | No. They are read-scope reads of the user's own mailbox that send nothing outside Tilo, so there is no outbox entry and no grant. | PRD 10.4, SEC-03 |
| BQ-TBD | What happens when triage itself fails for a message? | Not pinned by these tests. The builder chooses at-most-once (keep the claim, as the WhatsApp handler does) or retry, and documents the choice. | PRD 11.3, NFR-22 |
| BQ-TBD | Which event, if any, marks "mail triaged" or a watch failure? | None is required from FR-CHN-08. `mail_triaged` units are counted through `building.completed` (BQ-03) by FR-CHN-09. Anything emitted must be a registered type. | PRD 9.5, 14.2, BQ-03 |
| BQ-TBD | Are Gmail addresses kept out of logs? | Yes. They are personal data, so they are treated like full phone numbers in the channels logging rule. | PRD 16.1, services/channels/CLAUDE.md |
