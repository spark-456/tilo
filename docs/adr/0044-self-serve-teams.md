# ADR-0044: Anyone who signs in may join, found a team, lead it and invite others

- Status: **Accepted** (15 Oct 2026). The product owner asked, in chat at about 09:35 IST on 15 Oct 2026, that
  "anyone who creates an account should be able to be a team leader and invite others to work on their workspace",
  and approved this change to a frozen contract in the same chat with the words
  "approve contract change for self-serve teams". The change is additive: `person.schema.json` goes from 1.0.0 to 1.1.0 and every stored record
  and fixture stays valid. The code (`tilo_people`, `tilo-api`, the web) is a builder's ticket. (Next free number
  on every local and `origin/*` branch at 15 Oct.)
- Deciders: product owner (self-serve teams), architect (contract shape and rules)
- Requirement: SELF-SERVE-TEAMS; FR-PB-01, FR-PB-04, FR-CAL-06; PRD 10.1, 16.5, 23.5; ADR-0015, ADR-0016, ADR-0040
- Questions: BQ-SST-1 to BQ-SST-6 in `docs/open-questions.md`.

## Context
1. **One org, owner-run directory.** Tilo serves one org (`deps.ORG_ID`). people.rules.md PE-17 made every
   directory change an org owner's: only an owner creates a person, sets a role or assigns a membership, and "Terms"
   counted a membership only when an org owner assigned it. The org's owner is minted for the configured bootstrap
   uid (`TILO_PEOPLE_BOOTSTRAP_UID`), and only into an empty org. A signed-in judge may already join as a plain
   member (JUDGE-FIRST-RUN F1, code only, after founding).
2. **What the owner wants.** Anyone who signs in should be able to lead a team and invite people to work in it.
   Under PE-17 that needs the org owner for every person and every team.
3. **What membership grants.** A member of team T reads T's active team pins (PE-02), can be tagged on them (PE-06),
   reads teammates' directory view (PE-20) and busy intervals of their accepted calendar entries (PE-04), and reads
   any world shared with T as a team reader (PE-31, PE-32). Owners were trusted to decide this. A self-serve lead is
   anyone, so membership they assign must not let them watch a person who never agreed (PRD 23.5: Tilo never
   monitors individuals).

## Decision
1. **Self-join (PE-17).** Any person in a full web or mobile-web sign-in session that is not a demo session creates
   their own `person` record, before or after founding: own id, the server's org, `org_role: member`, no
   memberships, `created_by` themselves at the server clock. Only the bootstrap uid becomes owner, once per org,
   even after members joined. The bootstrap uid founds instead of joining. Single org stays: no per-user orgs.
2. **Two optional membership fields (`person` 1.1.0).** `lead` (boolean; written only as true; absent means not a
   lead) and `accepted_at` (a timestamp). `required` does not change.
3. **Terms (PE-02 amended).** A membership counts in one of three ways: an org owner assigned it (unchanged); it is
   the **founding** entry, `lead: true` self-assigned by the person whose entry for T is strictly the earliest in
   the org (a tie founds nothing); or it is an **invitation** by a lead of T, a lead since no later than the
   invitation, that the person accepted (`accepted_at` from the invitation to now). A **lead** of T is a member whose
   counting entry has `lead: true` under the first two ways. `lead: true` set by anyone else counts for nothing.
   An invitation lapses when its lead stops leading, and does not revive if they lead again.
4. **Self-serve teams (PE-37).** Any person creates a team: `tilo-api` mints an unused `tm_` id (at least 96 random
   bits) and writes the creator's founding entry. A lead adds a pending invitation for a person of the org and
   removes entries of their own team, except another person's lead entry. Only the invited person accepts. A person
   removes their own entry unless an owner assigned it. Only an org owner sets `lead` on someone, sets `org_role`,
   assigns or removes memberships of any team, and controls org switches, limits, budgets and org-wide tool access.
5. **Invitations need the invited person's acceptance.** This was not in the first request; it is the minimum that
   keeps PRD 23.5 and PE-20. Without it, anyone could create a team, add a stranger's address and read their busy
   calendar and name. The invited person reads the inviter's directory view while the invitation is pending
   (PE-20); the lead reads nothing of them until they accept, and every answer to an invitation is the same
   whether or not the address belongs to someone (no existence oracle).
6. **A team's lead is not the PRD 10.1 Team Lead.** `lead` manages that team's memberships and nothing else. It
   opens no gate, answers no card, holds no ADR-0006 domain and widens no world, policy, budget, connector or tool
   access. A world reaches a team only through its owner's `world_share` (PE-31), which is unchanged.
7. **No new event type.** Directory changes stay records with no world event, as before.

## Security
- Authorisation is decided server side by `tilo-api` from the verified session and the **stored** directory of the
  whole org: every person of `deps.ORG_ID`, not only the actor and the target. The founding check compares an entry
  with every other entry for that team, so a directory of two records would wrongly find a founder. Nothing comes
  from a request body, a header, a token claim, a model or sign-up input. Every stamp (`created_by`, `assigned_by`,
  `accepted_at`) is the session's person and the server clock (PE-19).
- Leads cannot escalate. They never set `org_role` or `lead` for anyone, never touch another team, never accept for
  someone, and never remove another person's lead entry. A `lead: true` they write would count for nothing. Their
  invitations count only after acceptance and only while they still lead.
- Demo, email, signed-link and world-bound sessions are refused for every write in PE-17 and PE-37.
- A world owner who shares a world with a team now trusts that team's leads, as well as org owners, with who reads
  it. The share stays the owner's to make and revoke (PE-31), and every reader is checked on every request (PE-32).

## Consequences
- `packages/contracts-py` and `packages/contracts-ts` regenerate `PersonMembership` with two optional fields.
  `contracts/fixtures/person.membership/` holds the shape fixtures and 46 crossref cases (`crossref/`). The
  reference check is `tests/contracts/_teams_lib.py`, and `_people_lib.is_member` now follows the amended Terms.
  Every existing crossref verdict stays the same, because no earlier record has `lead` or `accepted_at`.
- **For the builder** (no service code changes in this ticket): (a) `tilo_people.Directory.is_member` and a new
  `is_lead` follow the amended Terms, and `decide` gets the new actions, each with its team and target. (b)
  `change_person` and every lead check read the whole org directory, not `{me, stored}`. (c) `create_founder`
  founds while the founder marker is absent even if members exist. Self-join no longer waits for founding, is open
  to every full non-demo web or mobile-web session (not only judges) and refuses the bootstrap uid. (d) Routes for
  create, invite (by email, one answer), accept, decline, leave, remove and roster, and the web for them. (e) The
  `tilo_people` and `tilo-api` suites run `contracts/fixtures/person.membership/crossref/` and reach the same
  verdicts. (f) A security review before merge, because these are authorisation paths.
- An invitation the person never answers keeps one of their 8 membership slots until they decline it (BQ-SST-4).
- When a team's founder leaves or is deleted (PE-16), the invitations they made lapse. An org owner can name a new
  lead, and that lead invites the members again (BQ-SST-3).
