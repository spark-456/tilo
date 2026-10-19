# FR-MTG-08 explicit owner follow-up caller

This piece stacks on adopted draft #1002 at `cf7d6bbe`. It resolves the same verified
principal and request-scoped people/world/artifact/event dependencies as the minutes caller.
The returned caller samples the clock at invocation and delegates to `draft_owner_followup`.
Person IDs are resolved by the existing directory guard; arbitrary addresses are refused.
Default draft-store and scoped autopilot factories fail closed with 503 and no-store.

Offline acceptance covers sign-in/App Check before draft dependencies, default refusal,
T3/L1 directory-addressed cards, idempotent retry, confirmed-item nudges, expiry, wrong
owner, malformed meeting ID and meeting deletion during generation. No send is performed.
The existing adapter retains snapshot/retention checks and conservative per-unit SEC-16
accounting; this caller adds no price, provider mode, body budget or environment variable.

This is one bounded caller piece, not completed production wiring. Remaining chain work:
existing `/intake` allowance reservation and capped Router budget; durable DraftStore and
scoped card/outbox factories; minutes CAS/freshness integration; owner-only FlagStore routes
with registration off by default; whole-chain independent security review. #1002 stays draft.
No automatic attendance/read/confirmation trigger or real follow-up publication is claimed.

Run with `GOOGLE_LOCATION=asia-southeast1`, LIVE/TILO_RECORD unset and
`PYTHONPATH=services/channels/tests`: `uv run --offline --no-sync --all-packages pytest -q
services/api/tests/test_FR_MTG_08_owner_followup_caller.py`.
