# ADR-0024: Bot-hosted meetings and the meeting host account

- Status: Accepted (2026-10-06). Amendment 3 (the persistent browser profile, and the project-Owner exposure
  of the bot account) was Proposed and is ACCEPTED by the user on 7 Oct 2026 as a TEMPORARY, time-limited
  measure, on every hardening precondition below (see "Decision record, 7 Oct 2026"). MTG09-c is unblocked on
  those preconditions. The decision that
  the bot hosts and invites is the user's ("Have the bot
  start the meeting instead and then send invites to scheduled people", 6 Oct 2026, relayed by the
  supervisor). The open points were decided by the supervisor under the user's direct instruction ("For
  FR-MTG-09, you make the best decisions", 6 Oct 2026): see "Accepted amendments" below and
  `docs/open-questions.md` BQ-MTG09-13 to BQ-MTG09-19 (overridable by the user; BQ-MTG09-19 records the bot
  account tiloagent@gmail.com without 2-step verification). The rest is the architect's default,
  BQ-MTG09-2 to BQ-MTG09-11 (BQ-MTG09-1 and -12 are superseded). Amends ADR-0017.
  (Next free number on every remote branch at 2026-10-06; the merger may renumber.)
- Deciders: user (the scope change; approval of the ADR-0017 change), architect (design)
- Requirement: FR-MTG-09 (amended), FR-MTG-01, FR-MTG-10, FR-CAL-02, FR-CAL-04; PE-13, PE-14, PE-18, PE-20;
  PRD 3.4, 10.4, 16.1, 16.2; ADR-0016 decision 7, ADR-0017

## Context
FR-MTG-09 was a guest-join experiment: the bot joins an ordinary Meet with no account and the host admits it;
ADR-0017 allowed a signed-in bot account only if that failed. The user now wants the bot to start the meeting
itself and send the invitations. Only a meeting's organizer is its Meet host, so the bot must own the event.
Every person's Google Calendar grant is `calendar.readonly` (FR-CAL-08), and the token broker treats all of a
person's connectors as one Google grant (CON-D10).

## Decision
1. **The organizer is the meeting bot's own Google account**, the one ADR-0017 defines (created by the user;
   tiloagent@gmail.com today is also the project Owner login, see amendment 3(a)). Tilo connects it as a separate connector, `meeting_host`, with
   one action, `create_meeting_event` (`send`, T3, `approval`, irreversible). The person's own `google_calendar`
   connector stays read-only. Contract check: every record involved validates unchanged; no contract change.
2. **One scope on the bot account only:** `https://www.googleapis.com/auth/calendar.events.owned`, asked
   through the normal incremental consent (capability `send`) when the Owner first hosts a meeting. A person
   signs in to Google as the bot, in their own browser; Tilo never sees or types a password. The Meet link
   comes from `events.insert` with `conferenceData.createRequest` (`hangoutsMeet`) and
   `conferenceDataVersion=1`; no Meet API scope.
3. **Always a person.** The event invites at least the Owner, so `attendee_count > 0` and `new_recipients`
   apply (PE-14); the action is listed T3 as well. A gate card shows the title, the time in the Owner's zone,
   that a Meet link is made, that the host account sends the invitations and the exact recipients; the outbox
   entry equals it (CR-12, OB-05). Only the meeting owner approves, in a signed-in session; no policy, Team
   Lead or Approver opens it. Invitees are the Owner plus the meeting's attendees who resolved to Tilo persons
   of the same org, by addresses from their person records; nobody a model, a transcript or an email names.
   Guests cannot invite others, edit the event or see each other's addresses.
4. **The Meet link is never stored** (FR-MTG-01, `meeting.schema.json`). The insert asks Google for no link;
   Tilo keeps only Google's event id, in a receipt artifact. The bot gets the link in its start request: from
   the Owner's own invitation now, from an in-memory hand-over later (PPL-60c).
5. **Grant groups.** The token broker keeps the bot account's grant in its own group, so revoking it never
   touches a person's Google grant and the reverse. A consent answer for `meeting_host` that carries any other
   scope is refused as "not the bot account".
6. **ADR-0017 changes as follows.** (a) Its condition ("only if guest join fails") is lifted for bot-hosted
   meetings: the user's 6 Oct decision replaces the guest-first experiment (D-2), which is no longer required.
   (b) Its decision 2 said Tilo gets no Gmail, Drive or Calendar access to the bot account; Tilo now holds one
   OAuth grant on it with the single scope above, sealed by the token broker like every grant, and nothing
   else. (c) Replaced by amendment 3 (accepted by the user on 7 Oct 2026, temporary): the bot keeps ONE
   persistent, dedicated browser
   profile for its own account, signed in once by a human by hand; it is never in the image, the repository,
   a backup, Secret Manager or a Cloud Run service; the deployed services never hold or see that session; the
   exception ends at the hackathon freeze unless the user renews it. (The per-meeting noVNC sign-in on tmpfs
   of ADR-0017 is the fallback if the user withdraws the persistent profile; amendment 3's preconditions (a),
   (b), (d), (e) and (f) apply to it too.)
7. **What the bot does at meeting time.** Signed in as the organizer, it opens the link and enters as host
   without admission, posts the versioned disclosure first (FR-MTG-01), leaves on `Tilo leave` (FR-MTG-10) and
   never ends the call for everyone. It never clicks Admit (amendment 3(c)): invited
   attendees join under Meet's own rule for calendar-invited accounts, every knock from another account stays
   out, and a display-name allowlist is never used because it is spoofable; the meet-bot's `AUTO_ADMIT` stays 0
   for hosted meetings. The link is never written to the bot's `out/` files,
   logs, events or the package it hands to Tilo. Its persistent profile stays on its named volume between
   meetings (amendment 3, accepted 7 Oct 2026); if the user withdraws it, the ADR-0017 per-meeting terms apply
   and nothing stays after the run.

## Accepted amendments (supervisor, under the user's instruction of 6 Oct 2026)
These replace the text above where they differ. Amendment 3 was accepted by the user on 7 Oct 2026 (below).
1. The organizer is the bot's own dedicated Google account (decision 1 stands). Only the organizer is host.
   A person's grant stays `calendar.readonly`.
2. One scope, `calendar.events.owned`, on the bot account only; no Meet API scope (decision 2 stands).
3. **Decision 6(c) is replaced: ACCEPTED BY THE USER on 7 Oct 2026, as a temporary measure.** The bot keeps
   ONE persistent, dedicated browser profile for its own account, so it can enter as host at once. An agent
   cannot widen the PRD 16.1 rule 3 / 3.4 exception (BQ-MTG09-12 required the user's explicit yes for a
   profile kept between meetings); the user gave it, see the decision record below. **The gate, one wording
   for ADR, spec and supplement: MTG09-c is built only on the preconditions below; (a) is decided (accepted,
   time-limited) and the persistent profile is accepted, both by the user on 7 Oct 2026.** ADR-0017 decision 2
   covers tiloagent@gmail.com only on the terms of this amendment. The terms:
   the user signs the profile in once, by hand; Tilo never sees the password. It lives on the demo machine's
   own disk as a named Docker volume only (never a bind mount under the repository or OneDrive, never in the
   image, a backup, a Docker Desktop volume export or backup extension, Secret Manager or any Cloud Run
   service). Preconditions for MTG09-c: (a), (b), (d), (e) and (f) apply to EVERY signed-in session of the bot
   account in the hosting flow, per-meeting ones too (for a per-meeting sign-in, (b) means a random VNC
   password per run and VNC stopped once signed in); (g) applies to the persistent profile. All of them:
   (a) **Account separation, a user decision.** The documents used to say the bot account "is used by nothing
   else and holds no user data". That is false for tiloagent@gmail.com: it is the gcloud login on the demo
   laptop, the `tilo-dev` project Owner, the Firebase deploy login and the cost-alert inbox. A persistent
   cookie jar for it with no 2-step verification is a project-Owner session, and its theft reaches the KMS keys
   that seal every person's OAuth tokens, Firestore, Secret Manager, Cloud Run, Firebase and the spend. Either
   (preferred) the bot uses a NEW Google account with no role in the project or Firebase that receives no
   alerts (re-add it as the consent-screen test user), or the Owner, Firebase and alert roles move off
   tiloagent before the profile is signed in, or the user accepts the project-Owner exposure explicitly (their
   words and the date are recorded in the decision record below: the user chose the third option on 7 Oct 2026).
   It is time-limited: a dedicated no-role account replaces tiloagent before any wider use, and at the latest
   the exception ends at the freeze (17 Oct 2026) unless the user renews it.
   (b) **noVNC control.** The meet-bot starts `x11vnc -nopw -shared -forever` and websockify on every command,
   published on 127.0.0.1:6080. With a persistent profile that is a live signed-in browser that anything on
   the machine, or a web page opening `ws://127.0.0.1:6080/websockify`, can drive with no password. noVNC is
   therefore started only for the one-time `login` command, and then with a random password per run
   (`-rfbauth`, made in tmpfs and shown once in the user's terminal, never under /app, `out/` or `debug/`; VNC
   passwords stop at 8 characters, so VNC also stops once signed in and websockify gets an Origin check);
   `start`, `join` and every hosted-meeting run start no VNC. For a per-meeting sign-in (the fallback) the same
   rule applies: a random password per run and VNC stopped once signed in.
   (c) **Admission.** The bot is never given an invited-address list (Tilo hands it only the link, PPL-60c) and
   Meet's knock prompt shows only a display name, so "admit only invited addresses" cannot be enforced. The
   bot never clicks Admit: invited accounts enter by Meet's own rule, every knock stays out. MTG09-c refuses
   `--auto-admit` and `ADMIT_ALLOWED_NAMES` for hosted meetings and the report records that a knock stays out.
   (AUTO_ADMIT already defaults to 0 in the meet-bot.)
   (d) **Browser hardening.** No Chromium `--no-sandbox` while a signed-in profile renders Meet content; the
   `start` command (meet.google.com/new: hosting with no gate) and `join` of any link other than the one Tilo
   hands over are disabled for the persistent profile; `debug/` screenshots and caption HTML, which reach the
   OneDrive checkout through the `./:/app` bind mount, hold no link and no account page.
   (e) **Who can reach it.** Only the user's hand starts the bot container; `.claude/hooks/guard.py` gains a
   deny for `docker run`/`exec`/`volume` against the profile volume and for `bot.main` commands by any agent.
   (f) **Encryption at rest, stated honestly.** Chromium in the container has no OS keyring, so cookies sit in
   effect in plaintext in Docker's WSL disk (`docker_data.vhdx`, outside OneDrive). Only full-disk encryption
   protects it; the user confirms device encryption or BitLocker is on before the sign-in.
   (g) **Revocation and end of life:** the runbook below, owned by the user.
   The exception ends at the hackathon freeze (17 Oct 2026) unless the user renews it.

   **Decision record, 7 Oct 2026 (the user's own answers in the Google-lane session chat, given by selecting
   these options at a prompt; the supervisor had relayed the same words earlier, and that relay was not relied
   on).**
   - Question (a): "Do you accept the project-Owner exposure of tiloagent@gmail.com as the meeting bot's account
     for now, to be replaced by a dedicated no-role account before any wider use?" Answer: **"Yes, accept for
     now."** Relayed wording, same decision: "I accept the project-Owner exposure of tiloagent@gmail.com as the
     bot account for now; replace it with a dedicated no-role account before any wider use."
   - Question (persistent profile): "Do you also say yes to the bot keeping ONE persistent signed-in browser
     profile (amendment 3), as a temporary measure ending at the 17 Oct freeze unless you renew it?" Answer:
     **"Yes, temporary profile."** Relayed wording: "yes this is temporary measure, no worries".
   - Still the user's to do before the sign-in: confirm device encryption or BitLocker is on (f); sign the
     profile in once by hand (Tilo never sees the password). Still open for later: create the dedicated no-role
     account and move the bot to it.
   - Every precondition (a) to (g) and the runbook stand; the decision lifts only the "blocked" status.
4. Meetings are capped at 60 minutes (`meeting_host.max_duration_min`, free-account group limit). No paid
   Workspace; spending is the user's call.
5. The invitation is T3 through the outbox and a gate card; the event id derives from the outbox marker;
   `sendUpdates=all`; guests cannot invite others or see the guest list. The first real invitation goes only to
   `tilotesting@gmail.com`, after the user's one-word go; the live switch stays the user's.
6. Conversation quality: the cascade voice architecture already planned (`docs/VOICE_ARCHITECTURE.md`), not
   Gemini Live.

## Revocation and end of life (runbook; owner: the user; date: the hackathon freeze, 17 Oct 2026, or at once on any doubt)
1. In Tilo, disconnect `meeting_host` (the token broker revokes the grant).
2. At Google: Security, Your devices, sign out everywhere; review Third-party access and remove the Tilo
   client. A password change alone does not revoke Calendar-scoped tokens.
3. Change the account password.
4. `docker volume rm tilo-meet-bot_tilo_meet_profile` (the profile volume). This does not wipe the deleted data
   inside `docker_data.vhdx`, so the server-side sign-out in step 2 is what actually counts.
5. If the account holds any project role, check Cloud audit logs, IAM and service-account keys, and every
   connected app (gcloud SDK or Firebase CLI grants on other devices).
6. Check the recovery phone and email, and Gmail filters and forwarding (it is the cost-alert inbox, so an
   attacker could hide alerts).
User-side compensation for no 2-step verification (BQ-MTG09-19): a long unique password in a password manager,
the user's own recovery phone and email, Google security alerts on, a separate browser profile for the consent
sign-in (signed out afterwards), and the account address kept out of anything shown to judges.

## Alternatives considered
- *The Owner's own calendar as organizer* (FR-CAL-04's `create_event` with `calendar.events` on the person's
  grant): invitations come from the Owner, but the Owner is host and the bot is still a guest who must be
  admitted, which is what the user asked to remove; it also gives Tilo write access to a person's whole
  calendar and needs every test user to re-consent.
- *A Google service account*: a consumer account cannot delegate, and a service account cannot create Meet
  conferences without Workspace domain-wide delegation.
- *`meet.google.com/new` from the bot's browser* (the meet-bot's `start` today): no calendar invitation, and the
  link would have to travel by email or chat, so Tilo would store it.
- *`calendar.events`*: wider than needed (every calendar the account can edit). Kept as the fallback if Google
  refuses conference creation under `calendar.events.owned`.

## Consequences
- FR-MTG-09's acceptance moves to the bot-hosted flow (`services/connectors/tests/API_FR_MTG_09.md`); the
  supplement note `docs/prd-supplement-note-mtg09-2026-10-06.md` records it for the supervisor.
- The user adds `calendar.events.owned` on the OAuth consent screen and the bot account as a test user; no
  person re-consents.
- A free consumer bot account ends group calls at 60 minutes; `meeting_host.max_duration_min` (60) refuses a
  longer meeting until the user raises it.
- Only the person who connected the host account hosts with it, for their own meetings; sharing it across a
  team is a later decision.
- Cancelling or moving a hosted meeting (delete or patch with invitations) is a later T3 ticket.
