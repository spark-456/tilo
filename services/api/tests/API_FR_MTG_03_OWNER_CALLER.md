# FR-MTG-03 internal owner caller

`owner_minutes_caller.get_owner_minutes_caller` resolves the existing authenticated principal,
request-scoped people/world/artifact/event stores, redactor, clock and switches. The server-owned
budget dependency refuses503/not_configured by default. Neither a request body nor environment
variable enables this caller. Invalid budgets refuse503/no-store; mismatched request uid refuses404.

The returned caller accepts only a meeting ID and invokes `analyze_owner_minutes` for an explicit
owner instruction. Existing ownership, schedule, transcript retention, replay/demo, per-call reserve
and publication guards remain authoritative. The clock is read at invocation. Attendance, reads,
confirmations and follow-up drafting are unchanged; there is no production route or automatic trigger.

The HTTP path in the new test is registered only on an isolated FastAPI harness. It demonstrates
sign-in/App Check refusals, default-disabled refusal before store/provider use, foreign owner/world
refusal, missing/corrupt/future schedule refusal and replay/demo under outer LIVE without ledger spend.
Existing middleware remains required for any future production registration. This internal factory
does not independently install SEC-15/App Check middleware or define a public request contract.

Supervisor/API owner must adopt the integration design and separately review any production trigger,
server budget authority and activation settings before release. Slice2 Treasury/metering, durable-store
race integration, follow-up factories and private provider-quality acceptance remain separate work.
No route/contract/PRD, provider activation or real send is introduced by this slice.
