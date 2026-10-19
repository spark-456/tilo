# Supplement note: FR-MTG-09 becomes a bot-hosted meeting (6 Oct 2026)

For the supervisor to fold into `docs/prd-supplement-2026-10-05.md` (this file does not edit it). Design:
ADR-0024 (Accepted, 6 Oct 2026), `services/connectors/tests/API_FR_MTG_09.md`,
`docs/open-questions.md` BQ-MTG09-1 to BQ-MTG09-12. No contract change.

## Decision (user, 6 Oct 2026, relayed by the supervisor)

| ID | Decision |
| --- | --- |
| SD-05 (the supervisor assigns the number) | "Have the bot start the meeting instead and then send invites to scheduled people." FR-MTG-09's acceptance moves from guest-join to bot-hosted meeting plus invites. The meeting bot's own Google account is the organizer and Meet host (ADR-0024, amending ADR-0017). |

## Amended requirement

| ID | Requirement | Acceptance test | Pri |
| --- | --- | --- | --- |
| FR-MTG-09 | **Bot-hosted meeting.** For a scheduled bot meeting, the Owner asks Tilo to host it. The meeting bot's own Google account (connector `meeting_host`, scope `calendar.events.owned` on that account only) creates a Google Calendar event with a Google Meet link and Google invites the Owner and the attendees who are Tilo persons of the org. It is T3: the Owner approves a gate card showing the title, time, Meet link behaviour, sender and exact recipients, and the outbox sends exactly that. The Meet link is stored nowhere in Tilo. At meeting time the bot, signed in as that account (per meeting on ADR-0017's terms, or through one persistent dedicated profile if the user accepts ADR-0024 amendment 3), enters as host, posts the disclosure first and never clicks Admit | Fake Calendar transport: one `events.insert` with `conferenceData.createRequest` (`hangoutsMeet`), `conferenceDataVersion=1`, `sendUpdates=all`, attendees equal to the card's recipients; none before an approving `approval.resolved`; a retry makes no second event; a log, event and artifact scan finds no link. Report of the user's live run with test accounts in `docs/`: invitation from the host account, bot entered as host without admission, disclosure first; with amendment 3 accepted the persistent profile sits only on the demo machine's named volume, otherwise no profile or volume remains after the run; either way no cookie file or profile in the image, repo, backup, Secret Manager or any Cloud Run service | Must (fake flow and report); Should (Tilo launches the bot with the link, PPL-60c) |

## Knock-on changes

- **FR-MTG-01** (supplement 3.2): the Meet-link path becomes available for bot-hosted meetings once FR-MTG-09
  passes. Joining someone else's Meet as a guest stays unavailable (the guest-join experiment is not required).
- **FR-MTG-14, -15, -16** keep "depends on FR-MTG-09"; it now means the bot-hosted flow.
- **Addendum 3.1 FR-MTG-09 row and section 9 item 2** are superseded by the row above. Section 9 item 3 gains:
  add `https://www.googleapis.com/auth/calendar.events.owned` on the consent screen and the bot account as a
  test user; no person re-consents (people's Calendar stays `calendar.readonly`).
- **Plan rows (addendum 8):** PPL-60b (guest-join experiment) is replaced by MTG09-a (CL-REACH: connector,
  adapter, token grant groups, config, fake, live smoke script; security review), MTG09-b (CL-PEOPLE, CL-INT:
  `POST /v1/meetings/{id}/host`, fixed one-gate plan, S-26 button), MTG09-c (MEET: host join, never click
  Admit; unblocked on the ADR-0024 amendment 3 preconditions: on 7 Oct 2026 the user accepted the bot account's
  project-Owner exposure as time-limited and the persistent profile as temporary) and the user's live run with the report. PPL-60c (later) hands the link to the bot in memory.
- **CC-PEOPLE-2** config list: `meeting_host` in `config/connectors.yaml`, `create_meeting_event: T3` in
  `config/autonomy.yaml`, `meeting_host.max_duration_min: 60` in `config/personal.yaml` (MTG09-a adds them;
  B-007 regen by the orchestrator or the user).

## Still needs the user

1. Confirm ADR-0024 (it widens ADR-0017), or choose the Owner's own calendar as organizer (BQ-MTG09-2).
2. The bot Google account: decided on 7 Oct 2026, the user accepts tiloagent@gmail.com (today the project Owner login, ADR-0024 amendment 3(a)) for now and the persistent browser profile as a temporary measure; later a new account with no project role replaces it before any wider use. 2-step verification was declined by the user; never a password to Tilo or an agent. Still the user's: confirm device encryption or BitLocker is on, and sign the profile in once by hand.
3. Consent screen: the scope above and the bot account as a test user.
4. The first live run (`LIVE=1` is the user's): the smoke script, then a test meeting with test accounts only.
