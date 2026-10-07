# PRD supplement: Park City design handoff requirements, 6 Oct 2026

Status: **proposed for scope** (derived from `design_handoff_tilo_web_app/` and the 39 design requirements tracked on 6 Oct 2026); items marked *default* stand until the user changes them. `docs/prd/` stays read-only, so this supplement records the requirements introduced by the Park City web design handoff (`docs/web-app-rebuild-plan.md`). Precedence: `contracts/` > `docs/prd-supplement-2026-10-05.md` > this supplement > `docs/prd-addendum-people-agents.md` > the PRD (`docs/prd/tilo-prd-v2.md`).

Each requirement below is built as designed on labelled sample data first (`source: "fixture"`, with the persistent **Sample data** chip per HR-1..HR-7) and wired to live `tilo-api` endpoints as they land. MoSCoW priority defaults to **Should** unless the design makes the capability core to the Park shell, Home/Ledger decision loop, or policy/spend governance (**Must**).

## 1. Requirements from the Park City design (39)

### 1.1 Skill teaching and quality (`FR-SKL-01` to `FR-SKL-07` · Skills)

| ID | Requirement | Acceptance test | Pri | Page |
| --- | --- | --- | --- | --- |
| FR-SKL-01 | **Teach by showing.** Record my screen, guided walkthrough, describe it, or upload an example; captured steps list as you go. | Four captured steps enable "Show me Tilo's version"; nothing is sent anywhere while capturing. | Should | Skills |
| FR-SKL-02 | **Tilo's version.** Tilo restates the skill as steps, each with an "Ask me first" switch, one clarifying question and estimates. | Estimates show cost per run, time and how often it stops to ask, from the ledger's prices. | Should | Skills |
| FR-SKL-03 | **Try run.** A safe rehearsal that steps through the plan and pauses where you asked to be asked. | A try run sends and saves nothing outside Tilo; the result says how closely it matched you. | Should | Skills |
| FR-SKL-04 | **Save a skill.** Name, scope (just me or the team) and trigger (when I ask, a schedule, or an event). | A saved skill starts as Learning and appears in the library. | Should | Skills |
| FR-SKL-05 | **Rate and fix runs.** Thumbs up or down; a thumbs down asks which step went wrong. | A fix applies to the next run of that skill and is logged. | Should | Skills |
| FR-SKL-06 | **Trust and pause.** Run history bars, Mark as trusted or Keep learning, Pause and Resume. | A paused skill never starts; trusted needs a set number of good runs. | Should | Skills |
| FR-SKL-07 | **Who helped this month.** Answers and fixes per person, with the change in mistakes. | Shows counts only, never message content. | Should | Skills |

### 1.2 Tool access (`FR-ACC-01` to `FR-ACC-04` · Skills, Connectors)

| ID | Requirement | Acceptance test | Pri | Page |
| --- | --- | --- | --- | --- |
| FR-ACC-01 | **Off / Read / Draft / Act per tool.** One plain-language level for each connected tool. | Each level maps to a risk tier; Act never goes past what the policy engine allows. | Must | Skills, Connectors |
| FR-ACC-02 | **Per-skill tool access.** A skill can use a tool at a lower level than the team default. | A skill's level can only lower the team level, never raise it. | Should | Skills |
| FR-ACC-03 | **Connector detail.** Account, sync status with a spinner, scopes and "Used by" links. | "Used by" lists the skills and worlds that touch the tool. | Should | Connectors |
| FR-ACC-04 | **Reconnect and expiry.** A warning before a sign-in expires, and one-click reconnect. | The warning shows 3 days ahead; reconnecting never shows Tilo a password. | Should | Connectors |

### 1.3 Spend analytics (`FR-SPD-01` to `FR-SPD-08` · Ledger, Home)

| ID | Requirement | Acceptance test | Pri | Page |
| --- | --- | --- | --- | --- |
| FR-SPD-01 | **Five KPI tiles.** Spent so far, month-end forecast, waiting on you, saved by memory, hours handed back. | Every figure equals the credit ledger; "waiting on you" opens the world. | Must | Ledger, Home |
| FR-SPD-02 | **Spend over time.** Running total, forecast, even pace, budget line, today marker and a hover tooltip. | The forecast changes when a waiting approval is decided. | Should | Ledger |
| FR-SPD-03 | **Where it goes.** Spend by world, tool or agent as a donut with a legend. | The three views add up to the same total. | Should | Ledger |
| FR-SPD-04 | **Cost per run.** Sparkline per skill with the percentage drop since the first run. | Clicking a card opens that skill. | Should | Ledger |
| FR-SPD-05 | **Approval wait times.** A histogram, average wait by type, and an "Add a backup" call to action. | Adding a backup approver changes the shown wait. | Should | Ledger |
| FR-SPD-06 | **What Tilo gave back.** Memory savings by week and hours handed back by team. | Estimates are labelled as estimates and link to their method. | Should | Ledger |
| FR-SPD-07 | **Activity log.** Filter tabs, day groups, expandable rows, approve inline, open in world. | Approving from the log is the same single `decide()` call as everywhere else. | Must | Ledger |
| FR-SPD-08 | **Month export.** Export the month as CSV (accounting sync later). | The file matches the ledger rows for that month. | Should | Ledger |

### 1.4 Team governance (`FR-TEAM-01` to `FR-TEAM-06` · Team)

| ID | Requirement | Acceptance test | Pri | Page |
| --- | --- | --- | --- | --- |
| FR-TEAM-01 | **Invites.** Invite by email, a pending "?" member, resend or cancel. | Invite stays disabled until the email is valid; removing someone reassigns their worlds to the Owner. | Should | Team |
| FR-TEAM-02 | **Roles and spend limits.** A role per person and a personal spend limit. | You can't change your own role; limits feed the per-user cap. | Must | Team |
| FR-TEAM-03 | **Who signs off, and how fast.** Approvers per approval type, average wait, backup approver. | Arriving from the Ledger scrolls here and highlights the card. | Should | Team |
| FR-TEAM-04 | **When agents stop and ask.** Five switches for the team's stop-and-ask rules. | Must-ask rules from the PRD can't be switched off; every change is logged. | Must | Team |
| FR-TEAM-05 | **What each role can do.** An 8 x 4 permission matrix. | The matrix matches what the policy engine enforces. | Should | Team |
| FR-TEAM-06 | **Helped Tilo.** Count and bar per person. | Counts only. | Should | Team |

### 1.5 Settings (`FR-SET-01` to `FR-SET-05` · Profile)

| ID | Requirement | Acceptance test | Pri | Page |
| --- | --- | --- | --- | --- |
| FR-SET-01 | **Profile.** Name, email and other fields; Save shows a toast. | Saved values persist per user. | Should | Profile |
| FR-SET-02 | **Notifications.** A channel matrix per event, plus quiet hours. | Decisions always keep at least one channel; quiet hours never hide a gate. | Should | Profile |
| FR-SET-03 | **Appearance.** Day or night, and motion: lively, calm or still. | "Still" freezes the city; reduced-motion settings are always respected. | Must | Profile, Shell |
| FR-SET-04 | **Security.** Two-step verification, confirm-on-approve, signed-in sessions. | Sign out one session or every session except this one. | Should | Profile |
| FR-SET-05 | **Plan and billing.** Plan, seats, renewal date and invoices. | Display only until we decide; the PRD lists billing as a non-goal. | Should | Profile |

### 1.6 Shell, Home and Agenda extras (`FR-UX-10` to `FR-UX-18` · All pages)

| ID | Requirement | Acceptance test | Pri | Page |
| --- | --- | --- | --- | --- |
| FR-UX-10 | **Account menu.** Profile, Connectors, Team, Mobile app (concept) and Sign out. | Every item navigates; Mobile app opens a placeholder. | Must | Shell |
| FR-UX-11 | **Notifications popover.** Bell with unread dot; approved items turn into "You approved". | Each notification opens its world, Connectors or Settings. | Must | Shell |
| FR-UX-12 | **Loaders and transitions.** Boot splash, the world loader, page transitions and the progress bar. | Timings match the design; reduced motion turns them off. | Must | Shell |
| FR-UX-13 | **Home extras.** City map pins and the composer's quick, routine and workspace flow. | Starting work adds the world and toasts with Open. | Must | Home |
| FR-UX-14 | **Agenda boards.** Pinboard or grouped board, Tilo suggestions with Find a time or Block it. | Block it turns a suggestion into a Focus time pin. | Should | Agenda |
| FR-UX-15 | **Find a time.** Free slots for everyone shown as pulsing ghosts; booking adds the event and a pin. | Booking writes nothing to a real calendar without approval. | Should | Agenda |
| FR-UX-16 | **Calendar details.** Calendar chips, weekend toggle, day load, event panel switches. | The switches decide whether Tilo joins, takes notes and briefs. | Should | Agenda |
| FR-UX-17 | **Share to Slack.** Share a world link into Slack. | Sharing goes through the approval card. | Should | World, Worlds |
| FR-UX-18 | **More connectors.** Slack, Notion, GitHub, Xero, HubSpot, Stripe, Microsoft 365, Jira, BambooHR. | Each connects by OAuth through the MCP client; no passwords. | Should | Connectors |

## 2. Open decisions and defaults (`BQ`)

| ID | Question | Default (in force unless the user overrides) | Touches | Date |
| --- | --- | --- | --- | --- |
| BQ-DSN-01 | **Role names: `Member` vs `Team Lead` (`FR-TEAM-02`, `FR-TEAM-05`).** The Park design handoff uses four role labels (`Owner`, `Admin`, `Member`, `Guest` / `Viewer`) across the Team table and the 8 x 4 permission matrix, whereas PRD 3.4 and `contracts/` name `Owner`, `Team Lead`, `Approver` and `Viewer`. Which labels and mapping win? | **Default:** Park UI renders the design's verbatim copy in fixture mode (`design_handoff_tilo_web_app/inventory.md`); at the contract/policy boundary `Member` maps to the standard workspace member (`Viewer` / domain `Team Lead` where domain ownership is granted) and `Admin` / `Team Lead` maps to `Team Lead` + `Approver` without widening any policy-engine permission (FR-TEAM-05). Contracts (`person.schema.json`) are unchanged until an explicit contract bump is approved. | FR-TEAM-02, FR-TEAM-05, PRD 3.4, PE-17 | 2026-10-06 |
| BQ-DSN-02 | **Currency and unit: pounds (`£`) vs `credits` (`FR-SPD-01..08`, `FR-SKL-02`, `FR-TEAM-02`).** The design handoff displays amounts in pounds (`£`, e.g. `£3,420`, `£480/mo`), whereas PRD 14 and the ledger contract meter in integer `credits` with a configured currency conversion (`config/prices.yaml`). | **Default:** Fixture mode keeps the design's `£` strings verbatim and shows the shell's **Sample data** chip ("Northwind Ops is a fictional team. Amounts are examples (£), dates are September 2026."); live mode reads integer credits from the credit ledger and formats amounts using the configured unit/currency prop (`credits` with local currency equivalent from `config/prices.yaml`), never inventing an unrecorded exchange rate (HR-1). | FR-SPD-01..08, FR-SKL-02, FR-TEAM-02, PRD 14, BQ-WEB-1 | 2026-10-06 |
| BQ-DSN-03 | **Plan and billing tab (`FR-SET-05`): live billing vs display-only.** The Profile page includes a "Plan and billing" tab (plan tier, seats, renewal date, invoice rows), while PRD 23 lists billing and subscription checkout as a non-goal for the hackathon build. | **Default:** **Display-only** on clearly labelled sample/plan metadata (`FR-SET-05`). No payment processor, card capture, or invoice mutation endpoint is built; interactive actions on the billing tab either display the read-only plan state or toast that billing changes are not enabled in this prototype. | FR-SET-05, PRD 23 | 2026-10-06 |
| BQ-DSN-04 | **Tool access levels (`FR-ACC-01`, `FR-ACC-02`) vs PRD autonomy/risk tiers (`T0..T3`, `L1..L3`).** The design exposes four plain-language per-tool levels (`Off`, `Read`, `Draft`, `Act`). How do they map to the policy engine? | **Default:** Deterministic ceiling mapping enforced by code: `Off` blocks all calls to the connector; `Read` permits `T0` read-only actions; `Draft` permits `T0..T1` (drafts and internal staging, no external send); `Act` permits up to the team's policy-engine ceiling (`T2` within policy bounds; `T3` actions still require a human approval card and never auto-execute). A per-skill level (`FR-ACC-02`) can only restrict (`min(team_level, skill_level)`), never elevate. | FR-ACC-01, FR-ACC-02, PRD 10, SEC-03 | 2026-10-06 |
| BQ-DSN-05 | **Team helper metrics (`FR-SKL-07`, `FR-TEAM-06`) vs no-monitoring rule (`PRD 23.5`, `PE-01..07`).** The design shows "Who helped this month" on Skills and "Helped Tilo" on Team. How do they stay within PRD 23.5? | **Default:** Aggregate, opt-in workspace counts of resolved skill questions/fixes only—never message content, talk time, sentiment, response speed per person, or individual performance ranking. | FR-SKL-07, FR-TEAM-06, PRD 23.5 | 2026-10-06 |
