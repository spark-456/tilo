# ADR-0024: Bot-hosted meetings and the meeting host account

- Status: Accepted (2026-10-06). The decision that the bot hosts and invites is the user's ("Have the bot
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
1. **The organizer is the meeting bot's own Google account**, the one ADR-0017 defines (created by the user,
   used by nothing else, holds no user data). Tilo connects it as a separate connector, `meeting_host`, with
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
   else. (c) Replaced (Accepted amendment 3, BQ-MTG09-15): the bot keeps ONE persistent, dedicated browser
   profile for its own account, signed in once by a human by hand; it is never in the image, the repository,
   a backup, Secret Manager or a Cloud Run service; the deployed services never hold or see that session; the
   exception ends at the hackathon freeze unless the user renews it. (The per-meeting noVNC sign-in on tmpfs
   of ADR-0017 no longer applies.)
7. **What the bot does at meeting time.** Signed in as the organizer, it opens the link and enters as host
   without admission, posts the versioned disclosure first (FR-MTG-01), leaves on `Tilo leave` (FR-MTG-10) and
   never ends the call for everyone. It admits only invited addresses (amendment 3, BQ-MTG09-15): invited
   attendees join under Meet's own rule for calendar-invited accounts, a knock from any other account is not
   admitted, and a display-name allowlist is never used because it is spoofable; the meet-bot's current
   admit-everyone default is off for hosted meetings. The link is never written to the bot's `out/` files,
   logs, events or the package it hands to Tilo. Its persistent profile stays on its named volume between
   meetings (amendment 3).

## Accepted amendments (supervisor, under the user's instruction of 6 Oct 2026)
These replace the text above where they differ.
1. The organizer is the bot's own dedicated Google account (decision 1 stands). Only the organizer is host.
   A person's grant stays `calendar.readonly`.
2. One scope, `calendar.events.owned`, on the bot account only; no Meet API scope (decision 2 stands).
3. **Decision 6(c) is replaced.** The bot keeps ONE persistent, dedicated browser profile for its own account,
   so it can enter as host at once. The user signs that profile in once, by hand; Tilo never sees the
   password. The profile lives on the demo machine's own disk (a named volume outside the repository, the
   image, backups, Secret Manager and every Cloud Run service). The meet-bot's admit-everyone default is OFF
   for hosted meetings: it admits only invited addresses. The exception ends at the hackathon freeze unless
   the user renews it.
4. Meetings are capped at 60 minutes (`meeting_host.max_duration_min`, free-account group limit). No paid
   Workspace; spending is the user's call.
5. The invitation is T3 through the outbox and a gate card; the event id derives from the outbox marker;
   `sendUpdates=all`; guests cannot invite others or see the guest list. The first real invitation goes only to
   `tilotesting@gmail.com`, after the user's one-word go; the live switch stays the user's.
6. Conversation quality: the cascade voice architecture already planned (`docs/VOICE_ARCHITECTURE.md`), not
   Gemini Live.

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
