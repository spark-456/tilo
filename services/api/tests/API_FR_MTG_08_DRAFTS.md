# FR-MTG-08 durable draft seam

`deps.get_followup_draft_store` uses `store_door.open_api_store` and the existing
shared production client. Missing configuration is 503, with no memory fallback.
Owner follow-up callers resolve this seam; the Autopilot factory remains closed.
`orgs/{org}/followup_drafts/{sha256(JSON([owner,instruction]))}` stores one JSON
payload. Atomic Firestore `create` preserves the first writer; only AlreadyExists
returns false. IO failures return sanitized 503 without logging draft content.

Offline acceptance covers restart reads, concurrent service instances, owner/org
isolation, punctuation/emit-marker keys, nested lists and dependency forwarding.
The fake exercises create preconditions; a real emulator acceptance remains due.
Before route activation: integrate draft/marker retention and person deletion,
fresh source checks and publication CAS, durable scoped cards/outbox, default-off
owner routes, and security review of the exact complete minutes chain. This seam
alone does not authorize publication or sends, nor prove a real meeting call.
