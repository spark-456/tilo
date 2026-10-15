# CX-OPENQ-ROWS — current-base default audit

As-of base: `625517b157653e84fa3efc5251a2bcbf315788c5` (`origin/live13-candidate` when assigned). Later live14 changes are outside this audit.
Repository: "C:/Users/josna/OneDrive/Desktop/Claude Projects/Tilo". Source line numbers below refer to this base's `docs/open-questions.md`.
Boundary: 13 Oct 2026 00:00 IST inclusive = `2026-10-12T18:30:00Z`; Git committer time, including novel merge-resolution additions, rather than the prose date column.
Pre-boundary first-parent anchor: `125e83bae021d98c9b5af0b366a16f898e7ed7d1`. The whole reachable DAG is inspected; this anchor alone is not used as a lossy branch-only diff.
Coverage: 128 current source occurrences, 98 distinct full rows, 97 distinct BQ/question decisions. Exact duplicate full rows are grouped with every source line listed; different defaults/questions remain separate even when the BQ id repeats.
Thus BQ-M2-5, BQ-TEAMWORLD-8 and the two SIMPLE-RUN-2 versions must not be deduplicated by id. TEAMWEB rows dated 8 Oct entered through a 13 Oct merge and are included; editing an older row's default alone is not a new row.
Status means source inspection, not deployed verification: Implemented = inspected code/contract follows the condensed default; Partial = only some clauses hold or later work superseded a clause; Not implemented = current code differs (often intentionally superseded); Unverified = evidence cannot establish the decision/runtime claim.
This is a read-only source audit. No application tests, cloud commands, paid calls, deployments or owner decisions were performed. Priorities/new requirements are not invented here.

| BQ id | Source lines | Introduction | Default (condensed) | Current status and concrete evidence |
|---|---|---|---|---|
| BQ-PA06B-4 | 1009 | 73bfc49a | Public signed mail links; validate token before durable seams. | Implemented — E01 |
| BQ-PROV-4 | 1013 | 7346d275 | Record first, retry stable rating/fix event; Learn lists own newest 50; state-event hole remains. | Implemented — E02 |
| BQ-SETWEB-1 | 1018 | ed0f39bf | Explicit settings save, honest threshold/demo copy, account storage; design approval still requested. | Implemented — E03 |
| BQ-M2-1 | 1019 | b63aa3f4 | Live switch, approved price, project and spend meter required; shipped voice disabled. | Implemented — E04 |
| BQ-M2-2 | 1020 | b63aa3f4 | Synthetic keyed replay only; no meeting reply audio persistence. | Implemented — E04 |
| BQ-M2-3 | 1021 | b63aa3f4 | Use send_client_content(turn_complete=True); live protocol probe still pending. | Unverified — E04: call exists; no live probe run |
| BQ-M1-1 | 1022 | f11d4186 | Live Meeting host section and callback return to Connectors; old S-26 button removed with old UI. | Partial — E05; S-26 portion superseded |
| BQ-M2-5 | 1024,1076 | ed3f21be | Proposed public OIDC reserve/close routes, separate pins, closed 2 KiB body; owner choice required. | Partial — E06: code built inert; activation/owner approval unverified |
| BQ-M2-6 | 1025,1077 | ed3f21be | Process-local owner-bound attend nonce; expire/settle open claim and ledger holds. | Implemented — E06, E07; process-local limit remains |
| BQ-M2-7 | 1026,1078 | ed3f21be | Meter Live replies only; analysis/facilitation remain under meeting call counts. | Implemented — E08; extending metered kinds needs contract/price decision |
| BQ-M2-8 | 1027,1079 | a77828e1 | API prices bounded usage, charges at most hold; unpriced settles full unit. | Partial — E06: implemented; historical 8000 rate replaced by 9500 (E09); price approval pending |
| BQ-ADR42T1-1 | 1028,1080 | 5be22c9d | Bounded token counts and newline-safe claim/key schemas; contract-only slice. | Implemented — E10; routes now exist inert (E06), so original no-route statement is historical |
| BQ-M2-4 | 1029,1048,1119 | 291cd4b8 | Require LiveVoiceMeter; originally bot wiring absent. | Partial — E04 gate implemented; E07 now wires remote meter, superseding the original gap |
| BQ-M2-5 | 1030,1068,1120 | e730de93 | Send success marks reached; settle later failure, release only before send. | Implemented — E04: send_client_content sets call.reached |
| BQ-GOLIVE935-1 | 1031,1107 | 3b2c75f0 | Transactional uid/run/org-day/day counters, holds, durable replay switch; retries count once. | Implemented — E11; no deployment/IAM state checked |
| BQ-GOLIVE935-2 | 1032,1108 | 3b2c75f0 | Unreadable or malformed spend store fails closed; deployed has no memory fallback. | Implemented — E11, E12 |
| BQ-GOLIVE935-3 | 1033,1109 | 3b2c75f0 | Global contention accepted; originally no hold expiry or durable Treasury; manual switch reset. | Partial — E11 now expires holds and E13 supplies Treasury; original limitations partly superseded |
| BQ-GOLIVE935-4 | 1034,1110 | c953c7b4 | Meter model/safety calls at provider seams and settle reported usage. | Partial — E09, E12: seams present; original 8000 rate superseded by 9500 |
| BQ-GOLIVE935-5 | 1035,1111 | c953c7b4 | Missing deployed meter falls back to replay; scheduled/no-uid work and cached source screen stay replay. | Implemented — E12; this does not prove deployed configuration |
| BQ-GOLIVE935-6 | 1036,1112 | 48a2efb7 | Keep 80 INR/USD until owner changes it. | Not implemented — E09: now 9500, explicitly superseded by BQ-GOLIVE935-7 |
| BQ-M2-9 | 1037 | e6cf737e | Voice routes off=404; strict pins, OIDC, caps, price and settle checks when on. | Implemented — E06; off remains shipped operator gate |
| BQ-M2-10 | 1038 | d023eb65 | Expire claim holds after 3x timeout; one-hour ledger holds swept on reserve/tick. | Implemented — E06, E07, E11, E14 |
| BQ-M2-12 | 1039 | 04e040de | Initially remember any meter refusal as permanent for the meeting/instance. | Not implemented — E08: LiveVoiceRefused now transient/bounded and remember=False; superseded by BQ-M2-12a |
| BQ-M2-13 | 1040 | c64acf3b | Document API LIVE independence; rollout script still flags LIVE as forbidden. | Implemented — E15; documentation/runtime env discrepancy remains owner/operator follow-up |
| BQ-M2-12a | 1041 | 3a429d1c | Closed refusal words, bounded transient retries, no persistent memory for meter refusals. | Partial — E04, E08 implement behavior; voice.py accepts max 10, while row says 20; default 3 agrees |
| BQ-T3-1 | 1042,1113 | 2dfd07b7 | Durable append-once Treasury via API store door; demo memory/dev ledger; unreadable=503. | Implemented — E12, E13 |
| BQ-T3-2 | 1043,1114 | 2dfd07b7 | Own-user entries; 5000-entry whole-read cap; deletion and report rollups later. | Partial — E13: cap/audit remain; E13 rollups now replace route whole reads; erasure follow-up remains |
| BQ-T3-3 | 1044,1115 | 1e1735a4 | One Treasury commit after each settled live unit; best-effort failed write does not undo spend. | Implemented — E09: LedgerSink append_once and ERROR marker; durable retry remains future scope |
| BQ-T3-4 | 1045,1116 | 12dfceb5 | Fold unattributed request/task/world spend into own pseudo live run, not world report. | Implemented — E09, E13, E16; matching total is conditional on partial=False |
| BQ-T3-5 | 1046,1117 | beff25a1 | Write entry+rollup together; reports query own rollups; bounded buckets/pages, no backfill. | Implemented — E13 |
| BQ-T3-6 | 1047,1118 | beff25a1 | GET /costs marks totals below cap ledger or unreadable as partial. | Implemented — E16 uses current INR_MINOR_PER_USD; row literal 8000 is historical |
| BQ-TEAMWORLD-2 | 1050 | 9d602938 | Share target is world id; separate crossref fixture shape; same-org owner/reader checks. | Implemented — E17, E18 |
| BQ-TEAMWORLD-3 | 1051 | 9b49fd4c | Owner-only no-body share writes; stable retry stamps; bounded writes, erase shares, CAS storage. | Implemented — E17, E19 |
| BQ-TEAMWORLD-4 | 1052 | 56f3f256 | Fresh share-derived Viewer; team-only item projection and 200-row list; owner reads independent. | Implemented — E18, E20 |
| BQ-TEAMWORLD-5 | 1053 | 84258fb0 | Owner-only no-store share list with ordered lapse reasons. | Implemented — E17: list_team_shares and _reason |
| BQ-TEAMWORLD-F1F3 | 1054 | db010829 | Refresh lapsed grant; stable retry; CAS removal/revocation after failed event, residual risk logged. | Implemented — E17: _grant and _take_back; recorded residual remains |
| BQ-TEAMWORLD-6 | 1055 | 90aa43b9 | Share dialog reads own memberships plus existing share rows; reread after change. | Implemented — E21: TeamShare; self-serve labels may now be richer than original ids |
| BQ-TEAMWORLD-7 | 1056 | e3b9c605 | Initially infer team page for unknown live id; read-only lenses and named team rows. | Partial — E21, E22: access=team now controls entry; unknown ids no longer probe; superseded by line 1059 |
| BQ-TEAMWORLD-8 | 1057 | 3caf214c | Add item to Only me or current world; reset and reread; uncertain retry reuses key. | Implemented — E23 |
| BQ-TEAMWORLD-9 | 1058 | 3ad0cc53 | Latest valid owner-visible share event by sequence; historical line only, no inferred current state. | Implemented — E21: ShareLine and shareLine model; visibility expansion needs architect decision |
| BQ-TEAMWORLD-8 | 1059 | 1b5be544 | List freshly permitted shared worlds with access=team and one cursor; web opens only listed team worlds. | Implemented — E20, E22 |
| BQ-WLD12-1 | 1067 | 6747eef5 | Keep stage mode in old app pending Park stage design. | Partial — E24: mode survives in worldView; Root now mounts Park-framed WorldViewApp, superseding old-App mount |
| BQ-GOLIVE935-7 | 1069,1121 | bcf3f63c | Use 95 INR/USD metering constant. | Implemented — E09: INR_MINOR_PER_USD=9500; no current market-price claim made |
| BQ-LIVE-GLOBAL-1 | 1070 | e0a7156b | Global Google model endpoint with global price region; location guard only where priced. | Partial — E25: config/code match; actual deployed GOOGLE_LOCATION unverified |
| BQ-X-INH-1-COSTS | 1071 | 459ba955 | Defer conflicting dev costs 200 versus system probe 503; supervisor disposition required. | Unverified — E26: both expectations still present; no acceptance choice or tests changed |
| BQ-TEAMWEB-1 | 1073 | 4230c559 | Original team-only live Api fallback, id labels, no fake columns or sent-invite claim. | Partial — E27: compatibility path remains; configured people directory now takes priority per line 1075 |
| BQ-TEAMWEB-2 | 1074 | 4230c559 | Original Connectors uses team tool levels, no catalogue/connect operations. | Not implemented — E27, E05: catalogue and connection routes now used; original fallback default superseded |
| BQ-TEAMWEB-MERGE-27 | 1075 | 4230c559 | Read connector/people directory first; lazily open team settings; fallback only for NotBuilt. | Implemented — E27; original request for owner/security review is not proof of approval |
| BQ-BYOK-1 | 1081 | d31b31ed | BYOK after first live run; later pieces wait for owner IAM, shipping flag off. | Partial — E28: built inert with enabled=false; sequencing/live/IAM prerequisites unverified |
| BQ-BYOK-2 | 1082 | d31b31ed | OpenAI-compatible first; Google mode chosen by owner; never service-account JSON. | Partial — E28, E29: valid contract supports openai_compat only; Google requires owner/contract decision |
| BQ-BYOK-3 | 1083 | d31b31ed | Org/team only; personal-scope calls use Tilo key until owner opts in. | Implemented — E30: plan_unit personal_scope branch; production wiring remains absent |
| BQ-BYOK-4 | 1084 | d31b31ed | Example org daily maximum 10000 credits; owner sets deployed number. | Implemented — E28: day_cap_credits_max=10000; operator value unverified |
| BQ-BYOK-5 | 1085 | d31b31ed | No owner-typed endpoint; fixed operator-approved configured URL, no custom endpoint UI. | Implemented — E28, E31: profile base_url is config-only; new endpoint policy remains future scope |
| BQ-BYOK-6 | 1086 | d31b31ed | One shared replay/kill switch also stops org-key work. | Partial — E30 accepts replay mode before BYOK; live per-path integration still absent |
| BQ-BYOK-7 | 1087 | 3b42cb10 | Choose proxy variant P, no API credential lease; real traffic waits for scaling/owner prerequisites. | Partial — E28 proxy primitive exists; E32 no model RPC handler wired; scaling/activation unverified |
| BQ-BYOKC-1 | 1088,1122 | da702e55 | Closed PATCH; narrowing immediate, resume/widening requires fresh confirmed owner. | Implemented — E29, E33 |
| BQ-BYOKC-2 | 1089,1123 | da702e55 | Contracts allow openai_compat only, no Google mode/project fields. | Partial — E29 contract exact; E28/E33 retain inert Google cases awaiting contract decision |
| BQ-BYOKC-3 | 1090,1124 | da702e55 | No event trace.payer until owner-approved event schema change. | Implemented — E29: event trace has no payer; org payer remains internal only |
| BQ-BYOKC-4 | 1091,1125 | da702e55 | 2 MiB model RPC, bounded text-only messages, fixed usage/error shapes. | Partial — E29 defines wire bounds; E28 validates proxy replies; E32 has no wired generate RPC handler |
| BQ-BYOKC-5 | 1092,1126 | da702e55 | Closed bundle/key alphabet, person authz audit, current consent and no-store metadata. | Implemented — E29, E33; deployment remains inert |
| BQ-BYOKC-6 | 1093,1127 | da702e55 | Reconcile credential marker, contracts, reply/parts checks and owner-only errors; defer Google. | Partial — E28, E31, E33: core reconciled; routes still hand-validate, retain inert Google fields; no live wiring |
| BQ-BYOKC-7 | 1094,1131 | 04a64147 | Owner-view not_configured enum/active pairing additive fix; remove prior xfail. | Implemented — E29, E34: owner-only definition and reconciliation assertions present |
| BQ-BYOK-8 | 1095 | be04760f | Interim bundle-membership marker until credential:org contract lands. | Not implemented — E28/E31 now require credential:org; explicitly superseded by reconciliation |
| BQ-BYOK-9 | 1096 | be04760f | PATCH widening needs consent/fresh owner/act limit; narrowing immediate. | Implemented — E33: patch_key and _widening |
| BQ-BYOK-10 | 1097 | be04760f | Single org-owner key; own-org resolution; personal scope stays Tilo, no per-person keys. | Implemented — E30, E33: primitive boundary only, flag off |
| BQ-BYOK-11 | 1098 | be04760f | Proxy checks key state each unit, refuses/fallback only by consent; no API lease. | Partial — E30 checks reference/vault; E28 proxy exists; production path unconnected |
| BQ-BYOK-12 | 1099 | be04760f | Add Google auth_mode/project_id reference and matching request contracts. | Not implemented — E29 excludes those fields; E33 retains inert internal Google scaffold; needs contract/owner decision |
| BQ-BYOK-13 | 1100 | be04760f | Delete all vault versions/reference returns to Tilo; pause blocks unless fallback enabled. | Implemented — E30, E33: delete and pause branches; production vault unconfigured |
| BQ-BYOK-14 | 1101 | be04760f | Only plan_unit/ByokSpend/router seams; no production path/store wiring. | Implemented — E30, E12: seams remain; this default deliberately describes unimplemented integration |
| BQ-BYOK-WEB-1 | 1102 | c7d98b0b | Plan-and-billing owner form, member active/label view, demo sign-in note; design approval requested. | Implemented — E35, E03; visual owner approval unverified |
| BQ-BYOK-WEB-2 | 1103 | c7d98b0b | Web uses bundle list/cap/consent metadata without inventing fields. | Partial — E33 owner view serves metadata; E29 has no consent-text field; contract/API gap remains |
| BQ-BYOK-WEB-3 | 1104 | c7d98b0b | Claim save/remove only after well-formed write+reread; clear key; fixed errors and reauth hint. | Implemented — E35, E36 |
| BQ-BYOK-FIX-1 | 1105 | 54f4d8db | Reject unverified Vertex grant before side effects; pause only active, resume never calls vault. | Implemented — E33: VERTEX_GRANT_CHECKED=False and _mode/patch_key guards |
| BQ-BYOK-FIX-2 | 1106 | 219d1b62 | Minimum one-credit finite org reserve; missing bundle refused unless fallback allowed; honest owner state. | Implemented — E30, E33: MIN_RESERVE and _public missing-bundle branch |
| BQ-BYOK-RECON-1 | 1128 | 9155ddde | Reconcile org credentials/audit/replies; originally blocked owner not_configured enum. | Partial — E28/E31/E33 reconciled; E29/E34 now resolve original contract blocker, so strict xfail is obsolete |
| BQ-BYOK-RECON-2 | 1129 | 9155ddde | Keep Google scaffold unreachable; no Google fields in public answer; owner/contract decision pending. | Implemented — E28, E29, E33; Google production support remains blocked |
| BQ-BYOK-RECON-3 | 1130 | 9155ddde | Removal audit bundle/version both null, prior acts retain old values. | Implemented — E33: delete_key audit and _audit |
| BQ-BYOK-FIX-3 | 1132 | fd8813df | Text API-key field CSS-masked, manager hints off; page-owned consent version; newer server blocks send. | Implemented — E35; mask support warning remains |
| BQ-SIMPLE-RUN-2 | 1134 | ad472056 | Parse word deadlines; unique fields with date-word question replacement; vet sources, cap/start retry. | Partial — E37: core implemented, date-word replacement explicitly superseded by revised row 1137 |
| BQ-SIMPLE-RUN-1 | 1135,1138 | 184e3c61 | Skip Director questions, use recommended approach, one editable confirm and budget Start. | Implemented — E38 |
| BQ-OLD-UI-OUT-3 | 1136 | 5dc42189 | Move old Library/meeting/plate/calendar/replay functionality into Park and redirect old addresses. | Implemented — E39; old fixture screens removed, real hosting remains separate |
| BQ-SIMPLE-RUN-2 | 1137 | ad472056 | Revised SIMPLE-RUN-2: uniqueness by field only, no wording/date heuristic; remaining defaults unchanged. | Implemented — E37; revised row supersedes line 1134 question-selection clause |
| BQ-ASSUME-1 | 1139 | d7478c26 | Assume model ambiguity/tradeoff and record working event; rules/T3 still ask. | Implemented — E40; new dedicated assumption event/editable row requires contract decision |
| BQ-OWNANS-1 | 1140 | cf48f67e | Exactly option or typed text; typed text only question cards; bad request before writes. | Implemented — E41 |
| BQ-OWNANS-2 | 1141 | cf48f67e | MCP answer_card stays option-only; server/typed MCP extension later. | Implemented — E42 contract remains option-only; future MCP implementation/ADR outside this report |
| BQ-OWNANS-3 | 1142 | cf48f67e | Redact and safety-screen typed answer before event/agent; refuse while card stays open. | Partial — E41 redaction/screening precede event; downstream model instruction isolation unverified here |
| BQ-BUDGET-FLOOR-1 | 1143 | 851a54d5 | Originally floor run grant at 30 credits, bounded by run cap. | Not implemented — E43/E38 now floor at 60; mechanism survives, value superseded by BQ-BUDGET-FLOOR-2 |
| BQ-SEARCH-LIVE-1 | 1144 | 100aed84 | Reserve grounded search at expected output=1024; keep output cap and five-query reserve. | Partial — E44 core reserve matches; actual Vertex/NAT configuration unverified |
| BQ-STUDIO-1 | 1145 | cd234837 | Original six-destination Studio nav; defer Chat/Needs/search/bottom tabs. | Partial — E45: real Chat/Needs routes now built; still no invented search; original nav list superseded |
| BQ-STUDIO-2 | 1146 | 7c02fc24 | Still helper poses from real request; no stored quick history or unsupported controls. | Implemented — E45; motion/design approval remains owner choice |
| BQ-SST-1 | 1147 | 5fb9d98c | Lead invitation counts only after recipient accepted_at; owner assignments count immediately. | Implemented — E46 |
| BQ-SST-2 | 1148 | 5fb9d98c | Resolve typed invitation email server-side; one no-oracle answer, no mail/pending unknown address. | Implemented — E47 |
| BQ-SST-3 | 1149 | 5fb9d98c | Founder-leaving invitations lapse; owner-assigned membership cannot be self-left. | Implemented — E46, E47 |
| BQ-SST-4 | 1150 | 5fb9d98c | Pending invite occupies one of eight slots; own decline allowed; no expiry. | Implemented — E46, E47; pending-invite quota would require a new rule |
| BQ-SST-5 | 1151 | 5fb9d98c | No team name record; label self-serve team by roster lead display name. | Implemented — E47 and E51; a first-class naming record remains future ADR |
| BQ-SST-6 | 1152 | 5fb9d98c | Bootstrap uid founds owner, never self-joins; full non-demo members may self-join without judge gate. | Implemented — E48 |
| BQ-BUDGET-FLOOR-2 | 1153 | f732672a | Raise grant floor to 60, retain cap; rerun goes through approve. | Implemented — E43, E38: 60 in config/API/web; tasks.rerun routes through approve |
| BQ-INTAKE-DEADLINE-1 | 1154 | 9bc88d4c | 80s shared Director deadline, 0.6 first-attempt share, lost-reply idempotent retry, originally 100s web wait. | Partial — E49, E50: deadline/retry implemented; web wait is now 105000ms, superseding literal 100s |

Evidence index (paths are relative to the quoted repository and pinned to the as-of base; symbols explain the relevant behavior):

- E01: `services/api/src/tilo_api/plate_links.py:254` — public_link in access/App Check; peek precedes _public_seams and mark_no_person.
- E02: `services/api/src/tilo_api/skills_feedback.py:109` — stable retry events; skills_routes.py learn_route limits needs_rating to 50.
- E03: `apps/web/src/park/pages/Profile/ProfilePage.tsx:349` — saveUserSettings, sample refusal, notification Save, honest threshold at 536.
- E04: `packages/providers/src/tilo_providers/gemini_live_voice_adapter.py:201` — factory gates, replay key, send at 246, refusal handling at 319; voice.py build_voice_provider at 323.
- E05: `apps/web/src/park/pages/Connectors/MeetingHostAccess.tsx:55` — real host-account UI; oauth/CallbackPage.tsx:78 returns to Connectors.
- E06: `services/api/src/tilo_api/meeting_voice_meter.py:164` — off=404, pins/auth/body/caps; bounded_minor at 99; access/appcheck exemptions exist.
- E07: `services/api/src/tilo_api/meeting_voice_claims.py:87` — principal-bound nonce/find/end; meeting_bot.py:58 creates it; meet-bot/bot/cloud_worker.py:94 builds remote meter.
- E08: `meet-bot/bot/providers.py:374` — LiveVoiceRefused transient and remember=False; bot/voice_meter.py:last_refusal, meeting call cap at 362.
- E09: `services/api/src/tilo_api/spend_units.py:33` — 9500 constant, LedgerSink at 52, append_once, metered model/safety wrappers.
- E10: `contracts/meeting_voice_meter.schema.json:1` — token_count, closed message definitions; meeting_voice_meter.rules.md status/claim rules.
- E11: `services/api/src/tilo_api/spend_firestore.py:93` — transactional reserve/close; settle_expired at 142; switch and malformed-record guards.
- E12: `services/api/src/tilo_api/deps.py:811` — get_spend_cap_ledger; meter_for at 950; _live_or_replay at 1009; router_for_mode accepts optional org binding.
- E13: `services/api/src/tilo_api/treasury_firestore.py:169` — append_once transaction and rollup; MAX_ENTRIES/MAX_RUNS/MAX_BUCKETS/PAGE_MAX at 35.
- E14: `services/api/src/tilo_api/schedules.py:1` — _sweep_spend invokes ledger settle_expired best effort from tick.
- E15: `docs/routines-rollout.md:69` — Never still includes LIVE; docs/deploy-dev.md documents API voice-meter gate independent of LIVE.
- E16: `services/api/src/tilo_api/costs.py:107` — _partial compares settled_minor to current-rate totals and returns partial_reason.
- E17: `services/api/src/tilo_api/team_shares.py:67` — world-target private share event; stable stamps/_grant/_take_back; list route at 171.
- E18: `packages/people/src/tilo_people/access.py:40` — TEAM_ACTIONS/TEAM_VIEW and shared work-item checks; world_share.py:in_force checks owner/org.
- E19: `services/api/src/tilo_api/people_firestore.py:1` — people_world_share adapter; packages/people/src/tilo_people/stores.py:394 erase_person counts/deletes granted shares.
- E20: `services/api/src/tilo_api/deps.py:417` — fresh team_reader and team_readable_worlds; team_items.py projects items; worlds_list.py:180 lists permitted shared worlds.
- E21: `apps/web/src/park/pages/World/TeamShare.tsx:114` — directory memberships plus shares; ShareLine.tsx:20 historical copy.
- E22: `apps/web/src/park/pages/World/TeamWorld.tsx:26` — read-only shared world/items and directory names; worldModel.ts resolves listed access=team.
- E23: `apps/web/src/park/pages/World/AddWorkItem.tsx:56` — same text/place retains retry key; Only me at 115; reread list after success.
- E24: `apps/web/src/Root.tsx:26` — WorldViewApp lens chunk; worldView/StagePresenter.tsx:32 still uses useStageMode.
- E25: `config/prices.yaml:39` — region global; providers config price-region validation and Google adapter location logic.
- E26: `tests/system/test_SYS_prototype_flow_over_http.py:159` — PROBES requires costs=503; services/api/tests/test_DEV_HARNESS_dev_ledger.py:94 expects configured dev=200.
- E27: `apps/web/src/park/pages/Connectors/ConnectorsPage.tsx:121` — catalogue first, NotBuilt-only fallback; TeamPage.tsx:153 directory compatibility/settings at 372.
- E28: `packages/providers/src/tilo_providers/byok.py:115` — flag/closed loader, configured bundles, credential:org, proxy generation/reply guards; config/byok.yaml:22 disabled.
- E29: `contracts/org_model_key.schema.json:1` — closed key/patch/owner/audit defs, owner_last_error; byok.schema.json only openai_compat; model_call_rpc.schema.json text/bounds; event.schema.json has no payer.
- E30: `services/api/src/tilo_api/byok_unit.py:107` — plan_unit branches, scope/mode/ref/vault/fallback; MIN_RESERVE at 37 and in-memory ByokSpend.
- E31: `packages/providers/src/tilo_providers/config.py:214` — credential:org endpoint/provider/role restrictions.
- E32: `services/connectors/src/tilo_connectors/app.py:1` — app wires meeting-host/health routes; model_call_rpc generate handler absent from inspected service sources; no production proxy transport verified.
- E33: `services/api/src/tilo_api/byok_routes.py:113` — owner/fresh_owner; _public at 192, _audit at 222, _mode at 246, patch at 311, delete at 351; vault/store unwired=503.
- E34: `services/api/tests/test_BYOK_6_reconcile_977.py:1` — owner missing-bundle response conforms; invalid and valid PATCH fixture assertions; no strict xfail remains.
- E35: `apps/web/src/park/pages/Profile/ModelKey.tsx:143` — page-owned consent, key clearing, stale guard, CSS-masked text field and fixed write-result messages.
- E36: `apps/web/src/api/modelKey.ts:123` — model-key flow response validation and reread; unknown remote strings are not displayed.
- E37: `services/api/src/tilo_api/tasks.py:522` — loud start failure/granted retry; planning/due_dates.py:78 parses; planning/brief.py vets sources and intake questions are unique by field.
- E38: `apps/web/src/park/api/oneStep.ts:1` — skip questions, recommend/confirm path, floor/cap; Home presents one confirm.
- E39: `apps/web/src/park/app/router.ts:68` — legacy redirects; pages/Library and Agenda PeopleLists retain real records.
- E40: `services/harness/src/tilo_harness/must_ask.py:80` — model_questions switch; executor.py:409 records and passes assumptions; config/must_ask.yaml:8 assume.
- E41: `services/api/src/tilo_api/cards.py:642` — option/text exclusivity, question-only, redactor/check before event at 685.
- E42: `contracts/mcp_tools.schema.json:1` — answer_card_in requires option; typed text not added.
- E43: `config/run_grant.yaml:1` — min_run_grant_credits 60; deps.py fallback constant, tasks.py min_run_grant and rerun path.
- E44: `packages/providers/src/tilo_providers/router.py:636` — _search_quote uses expected output; config/expected_output.yaml:19 search=1024.
- E45: `apps/web/src/park/app/router.ts:37` — real chat/needs routes; chat/useQuickChat.ts request state, studio/Buddy.tsx still poses.
- E46: `packages/people/src/tilo_people/directory.py:75` — lead membership acceptance/lapse; teams.py:pending/decide_team and MEMBERSHIP_LIMIT.
- E47: `services/api/src/tilo_api/people_teams.py:49` — email body and fixed INVITED response; invite/accept/remove/roster paths.
- E48: `services/api/src/tilo_api/people.py:398` — bootstrap founding versus self-join; people_writes.py:544 creates plain member.
- E49: `config/intake.yaml:9` — 80 seconds, first_attempt_share=.6; intake_deadline.py and provider Router deadline cascade.
- E50: `apps/web/src/api/http.ts:90` — INTAKE_TIMEOUT_MS=105000; uncertain intake retry/stored-201 protocol at 615; intake_requests.py idempotency.
- E51: `apps/web/src/park/pages/Team/SelfServeTeams.tsx:32` — teamName selects the roster lead name, with generic Team fallback.

Owner/contract boundaries remain explicit: voice activation and price approval; Google BYOK/public payer schema and production wiring; custom endpoints/personal BYOK; unresolved dev-cost acceptance; design/motion/team-naming choices. Superseded prose is reported above rather than edited.

Reproducible audit validation from the branch root (Git/Python only; no application execution): run `python -c "from pathlib import Path;exec(Path('agy-bridge/reports/CX-OPENQ-ROWS.md').read_text(encoding='utf-8').split(chr(126)*3+'python')[1].split(chr(126)*3)[0])"`.
The check below recomputes introductions across source commits and dense combined merge diffs, compares exact current-row occurrence groups, verifies evidence locations against the pinned tree, and checks LF/single-report scope. It validates coverage and references, not the semantic judgment of each status.

~~~python
import re, subprocess
from pathlib import Path
BASE = '625517b157653e84fa3efc5251a2bcbf315788c5'
CUTOFF = '2026-10-12T18:30:00Z'
REPORT = 'agy-bridge/reports/CX-OPENQ-ROWS.md'
def git(*args):
    return subprocess.check_output(['git', *args], text=True, encoding='utf-8')
def key(line):
    cols = line.split('|')
    return (cols[1].strip(), cols[2].strip()) if re.match(r'^\|\s*BQ-', line) else None
source = git('show', BASE + ':docs/open-questions.md').splitlines()
current = {}
for n, line in enumerate(source, 1):
    if (k := key(line)):
        current.setdefault(k, {}).setdefault(line, []).append(n)
history = git('log', BASE, '--since-as-filter=' + CUTOFF, '--cc', '--format=COMMIT %H %cI', '-p', '--unified=0', '--', 'docs/open-questions.md')
introduced = set()
for block in history.split('COMMIT ')[1:]:
    header, *changes = block.splitlines()
    removed = {key(s.lstrip('-')) for s in changes if re.match(r'^-+\|', s)}
    introduced.update(k for s in changes if re.match(r'^\++\|', s) and (k := key(s.lstrip('+'))) and k not in removed and k in current)
expected = {(k[0], tuple(nums)) for k in introduced for nums in current[k].values()}
raw = Path(REPORT).read_bytes()
assert b'\r' not in raw and len(raw.splitlines()) < 400
text = raw.decode('utf-8')
actual = set()
for row in text.splitlines():
    if row.startswith('| BQ-'):
        cols = row.split('|')
        actual.add((cols[1].strip(), tuple(map(int, cols[2].strip().split(',')))))
assert actual == expected, ('missing', expected - actual, 'extra', actual - expected)
assert len(actual) == 98 and sum(len(nums) for _, nums in actual) == 128
refs = re.findall(r'^- E\d+: ' + chr(96) + r'([^' + chr(96) + r']+):([0-9]+)' + chr(96), text, re.M)
for path, line in refs:
    assert 0 < int(line) <= len(git('show', BASE + ':' + path).splitlines()), (path, line)
assert len(refs) == 51
subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, 'HEAD'], check=True)
assert git('diff', BASE, 'HEAD', '--name-only').strip() == REPORT
subprocess.run(['git', 'diff', BASE, 'HEAD', '--check'], check=True)
print('PASS: 98 full rows / 128 source occurrences; 51 evidence locations; LF; report-only scope; diff check')
~~~
