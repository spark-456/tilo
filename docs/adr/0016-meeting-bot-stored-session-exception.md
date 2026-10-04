# ADR-0016: Meeting bot session exception (only if guest join fails)

- Status: Proposed, conditional. Do not act on it unless the guest-join experiment (FR-MTG-09)
  fails; then it needs the user's approval before any such bot runs. (2026-10-05, architect; user
  decision D-2 of the addendum.)
- Deciders: user (approval, only if the condition holds), architect (proposal)
- Requirement: FR-MTG-09, FR-MTG-11; PRD 16.1 rule 3, 3.4, 16.2

## Context
PRD 16.1 rule 3: "Browser sessions are ephemeral; no cookies or sessions are stored between runs."
PRD 3.4 makes "storing or replaying passwords, cookies or browser sessions" a non-goal. The
standalone `meet-bot` signs in once to a consumer Google account through noVNC and keeps the
Chromium profile in a named Docker volume (`meet-bot/README.md`, `docs/ARCHITECT_BRIEF.md`), so
it joins as a signed-in participant. That is a stored browser session, even though the account is
the bot's own and holds no user data.

The user's decision (D-2): try **guest join first** (no account, no stored session). If guest join
is impossible, fall back to a dedicated bot Google account whose session lives only in the demo
container. Transcript or recording upload always stays in the deployed build.

## Decision (applies only if the experiment fails)
1. **Experiment first.** Join an ordinary Meet with a fresh browser context and no account; the
   host admits. Record browser, date, result and what the host sees in `docs/`. If it works, the
   bot uses an ephemeral context per meeting (tmpfs profile deleted at exit) and this ADR is
   withdrawn.
2. **Narrow exception.** If it does not work, one dedicated Google account ("Tilo notetaker",
   created by the user, used by nothing else, no Gmail, Drive or Calendar access for Tilo) may be
   signed in by a human through noVNC **inside the demo container**. The browser profile is on
   tmpfs or a volume removed with the container; it is never in the image, the repository, a
   backup, Secret Manager or any Cloud Run service. The container is started by hand for a meeting
   and removed after it.
3. **Not part of Tilo's runtime.** The deployed services (`tilo-api`, `-harness`, `-channels`,
   `-connectors`) never hold or see that session; the bot hands them a package (transcript, state)
   to the upload path. Credentials are never typed by an agent (16.1 rule 1).
4. **Disclosure and consent unchanged:** the bot posts the notice before capture, leaves on
   `Tilo leave`, and joins only meetings an Owner attested to (FR-MTG-01, -10).
5. **Lifetime.** The exception ends at the hackathon freeze unless the user renews it.

## Alternatives considered
- *Upload only, no live bot:* always available as the fallback; loses the live demo and the
  voice.
- *A hosted meeting-bot API:* rejected earlier (`VOICE_ARCHITECTURE.md` option 5): meeting content
  would leave Tilo's control.
- *The user's own account:* rejected; it would store a person's session.

## Consequences
- The deployed build keeps PRD 16.1 rule 3 whichever way the experiment goes.
- If the exception is used, `docs/` records the experiment result and the user's approval, and
  the `meet-bot` README states that the profile is ephemeral.
