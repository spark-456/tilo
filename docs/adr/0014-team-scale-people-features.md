# ADR-0014: People features at personal and team scale

- Status: Proposed. The decision is the user's answer of 2026-10-05 as relayed by the orchestrator;
  it amends the PRD's non-goals, so it waits for the user's confirmation of this text before the
  contracts branch (`feat/CC-PEOPLE-contracts`) merges.
- Deciders: user (decision), architect (record)
- Requirement: FR-MTG, FR-PA, FR-PB, FR-CAL in `docs/prd-addendum-people-agents.md` (PRD 3.4,
  23.3, 23.5, 10.1, 16.5)

## Context
PRD 3.4 lists "managing human staff, calendars or calls at company scale (workforce
orchestration, roadmap)" as a non-goal for this release. PRD 23.3 sketches people as first-class
actors (a people directory, calendar timetables, meeting transcripts with consent, a shared board,
agent supervisors through cards) as a 9 to 18 month roadmap item, and 23.5 says the world "will
not monitor individual employees". My first draft of the addendum (4 Oct) kept to personal scale to
stay inside 3.4.

The user then asked for more: "a personal scale, a team scale, and privacy of the personal scale is
important", a team pinboard every member can see next to a private personal one, and a calendar for
everyone.

## Decision
1. **Two scales.** *Personal*: a person's plate, work items, personal pinboard, calendar, meetings
   they own and their assistant panel. *Team*: a small team (a group of people an org owner puts
   together; proposed limits of 25 members and 8 teams per person, set in `config/personal.yaml`) with
   a team pinboard and a shared team calendar of entries a person chose to share. Nothing is
   company-wide: there is no org-wide directory view, dashboard or search of people's work.
2. **Personal data is private to its person.** No teammate, manager or org owner reads it
   (people.rules.md PE-01, PE-03 to PE-05). There is no manager view of a plate, and no ranking,
   activity score, talk time, sentiment or "who is behind" report anywhere, in any contract,
   screen, digest or assistant answer. PRD 23.5 stays a hard rule and is tested (E-PRIV).
3. **Team data is only what people put there.** A team entry is visible to the team's members when
   it is `active`; a Tilo-made entry becomes `active` only when the person who set it up (the
   meeting Owner) confirms it. Membership is a record on the person, assigned by an org owner
   (`person.memberships[].assigned_by`), checked at the time of each read, never inferred.
4. **Free/busy, not titles.** A teammate's calendar shows busy intervals for scheduling, never
   titles; only entries the owner shares reach the team calendar.
5. **Sending to another person stays T3** through the outbox, with a person's approval (PIN on
   WhatsApp), whatever the feature ("get in touch", minutes, follow-ups, invites).
6. **Scope of this amendment.** PRD 3.4's non-goal is lifted only for these features. Staff
   scheduling, time tracking, performance review, org-wide analytics, and org-wide directories stay
   non-goals.

## Alternatives considered
- *Personal only* (the 4 Oct draft): rejected by the user.
- *Manager visibility of team plates*: rejected; it is the monitoring PRD 23.5 forbids and would
  make the personal board unsafe to use.
- *A `team` record with its own owner and settings now*: deferred. Membership on `person` is enough
  for the MVP; a team's display name comes from org settings until a team record is needed.

## Consequences
- PRD 3.4 and 23.3 are read with this ADR. The PRD stays unedited (read-only); S0 may add a note
  to `docs/progress.md`.
- `contracts/people.rules.md` carries the visibility rules; `fixtures/person/crossref/` is the
  shared oracle that `tilo-api` (CL-PEOPLE) must pass.
- New eval group E-PRIV (12 cases, 100%) and privacy cases in E-RED guard the rule; a leak blocks
  deploys to `tilo-demo` like an injection failure.
- Risk R-new: the feature set widens the surface in a week with a hard date. The addendum's MVP cut
  line (section 8) and cut order protect the PRD 5.5 never-cut list.
