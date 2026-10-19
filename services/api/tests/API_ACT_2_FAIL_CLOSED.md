# ACT-2 — FR-MTG-03/08 allowance and EFF-03 verifier bounds

The owner dependency reuses intake's configured daily credit allowance and spend ledger;
#1056 bounds each request by committed UTC-day spend before the atomic reservation.
The internal caller and analysis/follow-up seams now require an explicit ledger and cap.
Missing ledgers refuse; offline fixtures supply in-memory ledgers rather than bypass metering.

Empty nudge results preserve cap/rate/replay refusals instead of returning successful `[]`.
Existing partial-card behavior remains: already created T3 previews are returned, with no send.
The verifier's configured input cap is 100000 tokens, matching the bounded transcript analyst.

`test_ACT_2_fail_closed.py` pins actual follow-up credit consumption, exhausted reservations,
missing ledger authority, cap/rate/replay refusal, and verifier input configuration.
The exact allowance-context rebind mutant is killed by the committed-spend assertion.
All checks use fake/replayed providers; activation and whole-chain review remain separate.
