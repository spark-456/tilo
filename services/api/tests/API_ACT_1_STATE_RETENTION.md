# ACT-1a: request-bound card and stop retention

Production factory cards, artifact indexes and stop rows reuse the SAME request-bound
FirestoreDraftStore's DraftRetention envelope/read policy. They carry the source and
exact deadline; every read and mutation rechecks source authority and the deadline.
Legacy, foreign-source and foreign-deadline rows cannot supply content. Updates use
Firestore update rather than set, so erased cards are not resurrected by an update.

Offline acceptance: test_ACT_1_state_retention.py plus existing state/factory/bound-draft
and request-binding suites. No providers, dispatchers or real messages are called.
ACT-1b must add indexed removal for cards/stops and called owner/expiry cleanup.
This slice alone does not satisfy ACT-1 or authorize activation.
