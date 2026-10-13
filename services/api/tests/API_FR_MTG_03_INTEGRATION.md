# FR-MTG-03: owner-scoped analysis and publication

`meeting_minutes.analyze_and_publish_minutes` connects the internal analyst to the
publication seam. It authorises the meeting owner and world, checks retention and
clean source screening, and reads only the stored transcript version through the
hash-checking artifact store before generation. Invalid sources never reach a provider.

The service caller supplies its already mode/spend-guarded Router, unit budget,
safety provider and trusted actual meeting start. This is an internal service seam;
no public route accepts a Router, transcript, date, budget or Minutes document.
Server directory records are used only for deterministic name/date resolution.
Directory records are never included in provider prompts.
The agenda comes from that stored meeting version. Analyst coverage must preserve
its titles/count/order and pass semantic verification using the pinned transcript.
An agenda edit during generation is covered by the same publication version guard.

Publication rechecks access and requires the meeting version captured before
generation. Any concurrent meeting edit refuses before writing a minutes artifact.
Existing publication CAS, event rollback, privacy and retention controls still apply.
Minutes remain unconfirmed; no derived item, recipient, card or outbox entry is made.

`meeting_analysis_mode.analyze_owner_minutes` is an inert internal request adapter.
It checks meeting/world ownership against the principal and verified request uid,
uses the stored scheduled start, and refuses unscheduled imports. Capture has no
persisted actual-start field; this adapter does not claim otherwise. Its credit
budget remains a trusted server input. Explicit mode reaches both provider factories;
demo sessions replay. Live safety/analyst/verifier calls each re-read switches and
team limits, reserve and conservatively settle the configured SEC-16 unit amount,
including invocation failures. This is not actual provider-cost measurement.
Team lowered-limit checks are per-call reads, not an atomic cross-store reservation.
No public endpoint or automatic post-attendance job invokes the adapter yet.

Remaining: recorded provider-quality E-MEET evaluation (the 12-case synthetic offline
acceptance gate is implemented), public mode/spend wiring, and the
confirmed-minutes FR-MTG-08 follow-up API integration. Review belongs to A/B/supervisor.

Offline acceptance: `uv run --package tilo-api pytest
services/api/tests/test_FR_MTG_03_analysis_publication.py -q -p no:cacheprovider`.
