# PRD supplement, 5 Oct 2026

Status: **in force for scope** (user decisions of 5 Oct 2026); the items marked *default* stand until the user changes them. `docs/prd/tilo-prd-v2.md` stays read-only, so this file records what changes. Precedence: `contracts/` > this supplement > `docs/prd-addendum-people-agents.md` (PR #303) > the PRD. Requirement IDs keep their meaning; an ID marked **Removed** is roadmap and has no ticket.

## 1. Decisions (user, 5 Oct 2026)

| ID | Decision |
| --- | --- |
| SD-01 | **WhatsApp is out of scope.** It is a future concept beyond this project. Every WhatsApp requirement, test, eval case, screen element and plan line is removed or rewritten below. The phone experience is mobile web; notifications are email (and web push, Should). |
| SD-02 | **In scope:** the Meeting Agent, the Personal Agent (plate and assistant panel), Pinboards and the Calendar integration from the people addendum v2 (PR #303), as amended in section 3. |

## 2. WhatsApp removal (SD-01)

### 2.1 Requirements

| ID | Change | New text, where amended |
| --- | --- | --- |
| FR-CHN-02 | Removed | — |
| FR-CHN-03 | Removed | — |
| FR-CHN-04 | Removed | The off-topic duty moves to the assistant panel (FR-PA-13, E-CHN in 2.3) |
| FR-CHN-05 | Removed | Card sync across channels is FR-HIL-11 |
| FR-CHN-06 | Removed | The kill switch is in the app (FR-HIL-07); email opt-out is the notification preferences on S-16 |
| FR-CHN-14 | Amended | Instruction typed on web or mobile web (mail card or assistant panel) to draft ready in ≤ 15 s p95 (EV-15). Test unchanged: 50 cases |
| FR-CHN-16 | Removed | Voice notes were a WhatsApp input; roadmap with it |
| FR-HIL-07 | Amended | Kill switch in the app. Test: `Stop all autopilot` sets all policies to L1 in ≤ 5 s; confirmed on web and by email |
| FR-HIL-11 | Amended | Cards on web, mobile web and email with the channel rules in 10.3. Test: the same card answered on mobile web closes on desktop web in ≤ 2 s |
| FR-INT-13 | Amended (Should) | A task can start from the assistant panel (S-30). Test: a panel instruction creates a task with a confirmation card |
| SEC-06 | Amended | Gate and T3 approvals need a signed-in web or mobile-web session; email links never approve a gate (10.3). Test: an approval without a signed-in session is rejected. No PIN |
| NFR-09 | Amended | Web instruction to draft preview (EV-15) ≤ 15 s p95 |
| EV-15 | Amended | Channel latency: web instruction received to draft shown, p95 ≤ 15 s |
| S-16 | Amended | Channels: email, notification preferences and connected Google accounts. No number binding |
| SC-02 | Amended | Email Autopilot: instruction on the phone (mobile web), email sent. Config: test Gmail account, autonomy level 1–2 |
| FR-CHN-01, -07 to -13, -15, -17, -18; NFR-06, NFR-21, NFR-22 | Unchanged | `tilo-channels` keeps email notifications, digests, web push and Gmail push |

### 2.2 Prose sections

Read "WhatsApp" as removed in: 1 (pillar table and summary: "reply from your phone" means mobile web), 2 (U2 decides on mobile web), 3 (PR-5: desktop, mobile web and email), 4.1 ("approve on your phone"), 6 (`tilo-channels`: email, web push, Gmail push; no webhook; Model Armor screens inbound email, not WhatsApp text), 10.3 (the WhatsApp row goes), 10.4 (kill switch in the app only), 11 (the WhatsApp channel row, number binding, business-policy and launch paragraphs go), 16 (the spoofed-command threat row and the WhatsApp consent line go), 17 (the WhatsApp messaging cost row goes), 18 (WhatsApp copy rules go), 20 (no WhatsApp test number), 21 (R-05 closed), 22 (OQ-09 closed; D-05 superseded by SD-01), 23 (WhatsApp joins Outlook, Teams and Slack on the roadmap). Section 25's "ask before sending any real email or WhatsApp message" stays as written.

### 2.3 Evals

| Group | Change |
| --- | --- |
| E-CHN (30) | Re-targeted: 30 off-topic messages to the assistant panel, 100% declined with what the panel can show (FR-PA-13). Count unchanged |
| E-RED (14) | The WhatsApp-spoofing cases become spoofed email senders (inbound `From` forged as a known contact). Count unchanged |

### 2.4 Contracts, code and infra (no new work, no contract change)

- `whatsapp` stays a valid channel value in the frozen contracts and fixtures: removing it is a contract change that buys nothing. No new code may emit or read it.
- WhatsApp code already on `phase0-stack` (`services/channels` webhook and binding, their tests, the 30 E-CHN files) stays dormant: not wired, not deployed, no secret values. Retiring or re-targeting it is ticket **CH-RM** (cleanup; tests that assert WhatsApp behaviour may be deleted with it, which is not weakening since the requirement is removed).
- Infra: the WhatsApp secret slots stay empty and go in the next infra batch.
- Open work that depended on WhatsApp is cancelled: CL-REACH "ticket 3" (WhatsApp T3 PIN, issue #307), issue #156 (FR-CHN-03/05 hardening), the WhatsApp parts of #197 and #298.

## 3. People features (SD-02): amendments to addendum v2

### 3.1 WhatsApp removed from the addendum

| ID | Change |
| --- | --- |
| FR-PA-04 | Removed (WhatsApp `PLATE`, `DONE`, `SNOOZE`) |
| FR-PA-02 | Test: web, the email digest and the panel show the same ids |
| FR-PA-05 | No proactive WhatsApp message. Nudges go to the panel (FR-PA-15) and the email digest (FR-PA-06) |
| FR-PA-08 | `STATUS` becomes a panel question ("what is the status of my tasks"), answered from the same read models. Should |
| FR-PA-11 | Test: a personal item never reaches a teammate through the API, the panel, the digest or a mention |
| FR-MTG-08 | Sending is T3, approved by the Owner in a signed-in session (SEC-06 as amended). No PIN |
| FR-PB-03 | Delivery is email (Gmail) and in-app only; the WhatsApp Should line is removed |
| Section 6.5, 6.7 | Remove "PIN on WhatsApp" and the WhatsApp paragraph |
| E-CHN +5 | The 5 plate-adjacent off-topic cases go to the panel group (2.3) |
| PPL-30 | Scope: sweeper, digest and panel nudges (no WhatsApp) |
| CC-PEOPLE (PR #304) | Remove the WhatsApp additions (commands, channel lists, fixtures) before merge |

### 3.2 Other amendments

- **FR-MTG-01:** the Must path is a transcript or recording upload. Adding a Meet link becomes available when the guest-join experiment (FR-MTG-09) succeeds.
- **FR-MTG-08:** drafting stays Must; the send is Should.
- **FR-PB-03:** the drafted message is Must; the send is Should.
- **FR-CAL-06:** split. Must: a person's calendar is private, and no teammate sees anything of it. Should: teammates see free/busy, as written.

### 3.3 Cut line for 10 Oct (*default*)

The addendum's cut line had about 40 Musts for 5 days while no service runs on tilo-dev yet. The cut below keeps one complete flow (meeting upload → verified minutes → plate → pinboards → calendar → panel) and moves the rest to Should, still in scope after the freeze if time allows.

- **Must by 9 Oct:** FR-MTG-01 (upload), -02, -03, -04, -05, -06, -07, -08 (drafts), -09 (experiment), -10; FR-PA-01, -02, -03, -07, -11, -12, -13, -14, -16, -17, -18, -19; FR-PB-01, -02, -03 (draft), -04, -05, -06, -07, -08; FR-CAL-01, -02, -03, -05, -06 (private), -08.
- **Should (after the core):** FR-MTG-08 and FR-PB-03 sends, FR-MTG-11 to -17; FR-PA-05, -06, -08, -09, -10, -15, -20; FR-CAL-04, -06 (free/busy), -07.
- **Cut first if behind:** FR-PA-06 digest, FR-PA-05 sweeper, the model fallback in FR-PA-14 (rules only).

## 4. Requirements agreed earlier that had no ID

| ID | Requirement | Acceptance test | Pri | Source |
| --- | --- | --- | --- | --- |
| FR-CON-15 | Every completed run delivers what its units really made, in-app and ungated. A run with no real artifact ends with an honest "nothing to deliver" and never mints an empty artifact | A run whose units made 2 artifacts delivers exactly those 2; a run with none shows the honest state and emits no `artifact.delivered` | Must | #283, BQ-218, PR #332 (merged) |
| FR-MEM-12 | Real (non-dev) runs store each unit output as an immutable, hash-checked, owner-scoped artifact version; `artifact.created` comes only from a stored record; delivery and the Verifier read the store | Per ADR-0017 once approved (8 tickets ready) | Must | #329, PR #331 (needs the user's contract approval, BQ-256..262) |
| GEN-01 to GEN-11 | Generality harness: held-out scenario bank of 30+ briefs on fakes in CI, live generator on `LIVE=1` only, static "no scenario in code" check, as specified in issue #272 | As in #272: bank invariants 100%; live 85% | Must (bank, static check); Should (live generator) | #272 |
| FR-INT-15 | A safe request outside what Tilo can fully do gets best effort first: it does what it can, says plainly what it could not do and offers alternatives. A hard refusal is only for safety or policy (FR-INT-12) | Eval: 20 partly-out-of-scope briefs each deliver the possible part and name the rest; 0 hard refusals among them | Must | user, 5 Oct |
| SEC-15 | Deployed access: sign-up asks "visitor or Google AI Builder Cup judge?". Visitors see "still under construction, not open to the public" and get no access; judges get live models (never forced to replay). Enforced server-side from the stored declaration | A visitor's API calls are refused server-side; a judge's run uses live models | Must | user, 5 Oct |
| SEC-16 | Per-uid rate limit and a lifetime spend cap of 1,000 INR per uid (config). The caps are the real protection, since the declaration can be bypassed | Over the rate limit gets 429; over the cap new work is refused with a clear message | Must | user, 5 Oct |
| NFR-27 | Owner alerts at 80% and 100% of a uid's cap and above a global daily threshold (alert-only), through a redacted structured log wired to a Cloud Monitoring email alert | Fake ledger crossing each threshold writes one redacted alert log line; no personal data in it | Must | user, 5 Oct |

## 5. Still needs the user

1. **Lovable and Canva connectors:** what should they do (create a design or deck, publish a site, import an asset) and through which route (MCP, API)? No IDs until then.
2. **Inbound-aware L2 for Email Autopilot** (#298, BQ-223): should L2 look at the inbound message too, so money or legal replies always need a person? The default is that it rides L2 as merged.
3. **ADR-0017 artifact store** (PR #331) and **ADR-0014 to -0016** (PR #303) sign-off; the ADR numbers clash with #285 and are renumbered in approval order.
4. **Gemini Live caps** (addendum section 4) and **teams** (who creates them, display names).
