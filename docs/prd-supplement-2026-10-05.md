# PRD supplement, 5 Oct 2026

Status: **in force for scope** (user decisions of 5 Oct 2026); the items marked *default* stand until the user changes them. `docs/prd/tilo-prd-v2.md` stays read-only, so this file records what changes. Precedence: `contracts/` > this supplement > `docs/prd-addendum-people-agents.md` (PR #303) > the PRD. Requirement IDs keep their meaning; an ID marked **Removed** is roadmap and has no ticket.

## 1. Decisions (user, 5 Oct 2026)

| ID | Decision |
| --- | --- |
| SD-01 | **WhatsApp is out of scope.** It is a future concept beyond this project. Every WhatsApp requirement, test, eval case, screen element and plan line is removed or rewritten below. The phone experience is mobile web; notifications are email (and web push, Should). |
| SD-02 | **In scope:** the Meeting Agent, the Personal Agent (plate and assistant panel), Pinboards and the Calendar integration from the people addendum v2 (PR #303), as amended in section 3. |
| SD-03 | **Build partners (user, 5 Oct).** When a person's task needs something built, Tilo helps them get it built with outside tools: a website or app front end through Lovable, decks and documents through Canva (for internal or external use, with the company data the person grants), and vendor-facing sites for third-party access and tracking. Tilo understands the requirements first and sends anything out only after the person accepts them. Example: for an Amazon-like competitor, Tilo prepares the storefront brief and hands it to Lovable as a direct prompt once the client has accepted the requirements. Section 6. |
| SD-04 | **Settled under the user's "yes to all" (5 Oct):** ADR numbers by approval order (0014 scenario config, 0015 to 0017 people, 0018 artifact store); the artifact store's logged defaults, with BQ-262 = FR-CON-15; inbound-aware L2 (a money, legal or spoofed inbound makes the reply T3); Gemini Live caps as proposed; the org owner creates teams; generator cap INR 150 per run. Live test spend is approved; the user still sets `LIVE=1`. |

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

Items 1 to 4 of the first version are settled (SD-03, SD-04). Open: none beyond the infra apply and live runs only the user can do.

## 6. Build partners (SD-03)

Routes checked on 5 Oct 2026: Lovable offers "Build with URL" (a link that pre-fills a prompt; no key; the person presses send in Lovable) and an official MCP server (`mcp.lovable.dev`, OAuth: create a project, send messages, read status, deploy). Canva offers the Connect API and an official MCP server (`mcp.canva.com`, OAuth: create designs, upload assets, export PDF or PPTX; brand-template autofill needs a Canva Enterprise plan). Both are external services: they get the same treatment as every connector (PRD 12, token broker, outbox, policy engine). MCP endpoints are called by Tilo's connector code; a model never holds the token or picks the tool freely.

| ID | Requirement | Acceptance test | Pri |
| --- | --- | --- | --- |
| FR-CON-16 | **Build handoff.** A build partner is a `Connector` with a typed `build_handoff` action. Its input is the person-accepted requirements for one deliverable (the approved approach and the deliverable spec, never the raw thread). The `writer` role turns them into the partner's prompt, and the person sees the exact prompt and the data it carries on a card before anything leaves. Sending is `data.transfer`, so it is T3 and always needs a person. The result (link, project id, status) is stored as an artifact with provenance (FR-CON-10, FR-MEM-12) | No outbox entry before an approving `approval.resolved`; the prompt sent equals the prompt shown, byte for byte; a requirement the person did not accept never appears in the prompt | Must |
| FR-CON-17 | **Lovable, link route.** For a website or app front end, Tilo makes a Lovable "Build with URL" link from the accepted requirements. The person opens it and presses send in Lovable. No key and no Tilo token; nothing leaves Tilo until the person clicks. The link is recorded as the deliverable | The link decodes to the approved prompt; it stays under the URL length limit, or Tilo says the brief is too long and offers the MCP route; no call to Lovable from Tilo | Must |
| FR-CON-18 | **Lovable, MCP route.** With the person's OAuth grant, Tilo creates the Lovable project, sends follow-up change requests from later accepted changes, and reads build status back into the world. Publishing or deploying is T3 | Fake MCP server: create, message and status calls are recorded; deploy never runs without approval; a revoked grant stops every call | Should |
| FR-CON-19 | **Canva decks and documents.** With the person's OAuth grant, Tilo creates a presentation or document from approved content, uploads only the company assets the person granted for this task, and exports PDF or PPTX back into Tilo as an artifact. It uses brand-template autofill when the person's Canva plan allows, and plain design creation otherwise. Internal use stays in the person's Canva; sharing outside the company is T3 | Fake Canva API: the design holds only approved content and granted assets; the export is stored with provenance; an external share needs an approving event; a non-Enterprise plan falls back without an error | Should |
| FR-CON-20 | **Granted company data only.** A build partner receives only data the person granted for that task (named files, folders or records, listed on the card), after the secret redactor (SEC-01) and the safety screen. A grant is per task, expires with it, and can be revoked | A file outside the grant is never uploaded; a secret in a granted file is redacted; revoking mid-task stops further uploads | Must |
| FR-CON-21 | **Vendor-facing sites.** When a task involves third-party vendors, Tilo can prepare a vendor-facing site (through FR-CON-17 or -18) that gives vendors access to what they need and lets the team track status (quotes, orders, deliveries). Access is by invite or link from the site's own platform; Tilo never handles passwords (hard rule). Tracking reads only pages or APIs the person connected | A vendor site brief carries only approved fields; no credential is stored or typed by Tilo; status updates come from recorded reads only (HR-1) | Could (interpretation of "3rd-party vendor side websites"; the user may refine) |
| FR-CON-22 | **Shown in the world.** A build handoff appears as an external pier or building, labelled with the partner. Its state changes only on recorded events: card approved, link opened (when the person returns), and status read over the MCP route | FR-WLD-03 coverage for the new events; no animation without an event | Should |

**Scenario rule:** an "Amazon-like competitor" run uses the same code as any other task. The build partners are configured connectors, never scenario code (PRD 4.3).

**Evals (E-BUILD, 8 cases):** 4 handoffs whose prompts must hold only accepted requirements (100%); 2 where unaccepted or ungranted data is planted (0 leaks); 2 over-long briefs (fall back to the MCP route, no truncation without saying so).

**Order:** after the deploy (P0-07a) and the people core. FR-CON-16, -17 and -20 are small (link route, no external calls) and fit before the 10 Oct freeze. FR-CON-18 and -19 need OAuth apps the user registers with Lovable and Canva, so they come after the freeze if time allows.
