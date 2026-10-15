# ADR-0046: Signed, single-use, expiring team invite links

- Status: **Accepted** (16 Oct 2026). Asked in chat to "reply 'yes, invite by link' if you want team invites by
  link", the product owner answered "Sure go on" at about 00:30 IST on 16 Oct 2026. That approves this change to the
  frozen contracts. It is additive: a new `team_invite_link.schema.json` 1.0.0, registry 1.5.0 to 1.6.0 (registry
  schema 1.2.0 to 1.3.0) with three event types, and people.rules.md PE-38 and PE-39 with PE-17, PE-19 and PE-37
  amended. Every stored record and fixture stays valid; `person.schema.json` stays 1.1.0.
- Supersedes the design-only proposal on `cx/INVITE-LINK` (5e95a373, file `0045-signed-single-use-team-invite-links.md`,
  never merged). Its threat model is kept. This ADR differs in five ways: no `person` change, three registered
  events (the supervisor's brief), a fixed 7-day life, a token that names no org or team, and one answer to a revoke.
- Deciders: product owner (invites by link), architect (contract shape and rules).
- Requirement: SELF-SERVE-TEAMS (INVITE-LINK); ADR-0044; PRD 10.1, 16.5, 23.5; SEC-10.
- Questions: BQ-INVL-1 to BQ-INVL-5 in `docs/open-questions.md`.

## Context
ADR-0044 lets a lead invite a person by email, and only a person who already has a record (they signed in once).
The owner wants a lead to share a link instead: whoever opens it, signs in and accepts, joins the team. A link is a
bearer secret, so it must be single-use, expire, be revocable, never become a membership or existence oracle, and
never let a lead do more than an email invitation already lets them do.

## Decision
1. **The link is a stored record plus a signed token.** `team_invite_link` (tilo-api's own record, at
   `orgs/{org}/team_invite_links/{id}` on the people stores' client) holds `id` (`til_` + 96 random bits as hex),
   `org_id`, `team`, `created_by` (maker, server clock), `expires_at`, `key_id`, `nonce_sha256`, `status`
   (`pending`, `redeemed`, `revoked`; never back to pending) and the `redeemed`/`revoked` stamps. Expiry is derived
   (`now >= expires_at`), never stored. No token, nonce, signature or URL is ever stored, logged or put in an event.
2. **Token.** `v1.<kid>.<invite_id>.<nonce>.<sig>`: `nonce` is 32 CSPRNG bytes, `sig` is
   HMAC-SHA-256(key[kid], `b"tilo.team-invite-link.v1\x00" + ascii("v1.<kid>.<invite_id>.<nonce>")`), both base64url
   without padding (43 characters). The parser is one closed regex
   (`v1\.[A-Za-z0-9_-]{1,32}\.til_[0-9a-f]{24}\.[A-Za-z0-9_-]{43}\.[A-Za-z0-9_-]{43}`, at most 200 characters) plus a
   canonical base64url round trip. The algorithm and version are fixed in code; an unknown `kid` fails. The key comes
   from `TILO_INVITE_LINK_KEY` (32+ bytes, Secret Manager, used for nothing else) and `TILO_INVITE_LINK_KEY_ID`
   (default `key_a`); unset or short, making and redeeming answer 503 `not_configured` (BQ-INVL-1). The token names no org, team or expiry:
   those are read from the record, so a link shows nothing about the team to whoever holds it.
3. **Make (PE-38).** `POST /v1/teams/{team}/invite-links`, body `{}`: a lead of T or an org owner (T must have an
   entry in the org), full web or mobile-web sign-in, not demo, not world-bound (PE-37's session rule). Life is
   exactly 7 days (`expires_at = created_by.at + 7 d`; the rule allows at most 7). At most 10 pending, unexpired links
   per team (429 `too_many_links`), and every POST counts against `write_limit` (60 a minute, SEC-10). Refused while
   `now` is not strictly later than every `lead: true` entry for T (409 `retry`): an entry stamped at a founding
   instant would tie with it and found nothing. Answer 201 `{invite_id, token, expires_at}`: the token is returned
   this once and never again. The web makes `<its own origin>/join#<token>`.
4. **List and revoke (PE-38).** `GET /v1/teams/{team}/invite-links` (lead of T or org owner; others 403) returns
   `{id, created_at, expires_at, state}` rows, `state` one of `unused`, `expired`, `used`, `withdrawn`; never a token,
   digest, key id or who used it. `POST /v1/teams/{team}/invite-links/{invite_id}/revoke`, body `{}`: a lead of T or an
   org owner gets `{"status": "done"}` whether or not anything changed (unknown id, another team's link, used,
   revoked); the compare-and-set `pending` to `revoked` happens only when PE-38 grants it. Others 403. Revoking a used
   link removes nobody; the member is removed with `remove_member` (PE-37).
5. **Redeem (PE-39).** `POST /v1/team-invite-links/accept`, body `{"token": "..."}` (never a query, path or GET; a GET
   consumes nothing, so link previews and scanners cannot redeem). The session is PE-37's and carries a
   Google-verified address (`Principal.verified_email`), else 403 before any lookup. The redeemer must already have
   a record in the org (the web calls `POST /v1/people/first` first) whose `email` equals that address ignoring case.
   The decision reads the stored link and the whole org directory: signature, `kid` equal to `key_id`, SHA-256 of the
   nonce equal to `nonce_sha256` (constant time), same org, `pending`, `now < expires_at`, no entry of the redeemer for
   T, fewer than 8 entries, and the new entry `{team, assigned_by: link.created_by, accepted_at: now}` must count
   under "Terms" while every current member of T stays one. Copying `created_by` makes the maker's authority checked
   at making and at redemption with no revival: a lead's link lapses when they stop leading, as their email
   invitations do.
6. **One answer.** Every refusal of a well-formed request is `404 {"detail": "invite_unavailable"}`: malformed,
   bad signature, unknown kid or id, wrong nonce, another org, expired, used, revoked, a lapsed maker, no record,
   another address, already in the team. The single exception is `409 {"detail": "membership_limit"}` (8 entries),
   given only when everything else grants, and it consumes nothing. Success is `200 {team, state: "member"}`.
7. **Single use without a two-document transaction.** The link's compare-and-set `pending` to `redeemed`
   (`redeemed: {by: redeemer, at: now}`) is the commit point: one winner, a lost race is the 404. The membership is
   written next by the person's compare-and-set (re-decided on a fresh directory, at most three tries). If that write
   or the event fails, the membership is undone, the link stays used (never back to pending, fail closed) and the
   answer is 503; the lead makes a new link (BQ-INVL-3).
8. **The joiner learns the team only after accepting.** Before, the page says only that this is a team invitation
   on Tilo. After, the answer names the team id and the web reads the roster (`read_roster`), whose lead's name labels
   the team (BQ-SST-5).
9. **Leaving (PE-37 amended).** A person removes their own entry unless an org owner assigned it **and** they never
   accepted it. An entry written by an owner's link carries `accepted_at`, so its person may leave it.
10. **Events (registry 1.6.0, family `invite_link`).** `invite_link.created` (`invite_id`, `team`, `expires_at`),
    `invite_link.accepted` and `invite_link.revoked` (`invite_id`, `team`), each in the actor's own Desk world (PE-12),
    actor and target the actor, `district` null, `vis: []`, `authz` null, not a side effect (a membership is not a
    send), written by tilo-api after its record commits. Created: an event failure removes the new link and answers
    503 (the token was never shown). Revoked: the revocation stays and the identical retry writes the missing event
    (part id from the invite id). Accepted: decision 7. This departs from ADR-0044 decision 7 for links only
    (BQ-INVL-5); email invitations still write no event.

## Security
| Threat | Control |
| --- | --- |
| Forged or edited token | HMAC with a domain-separated input, fixed version and algorithm, closed parser, constant-time compares; then the stored record decides. |
| Leaked or forwarded link | It needs a full Google sign-in with a verified address and the person's own record; it redeems once, lives 7 days and can be revoked. The make page says whoever opens it first can join. |
| Replay and races | The link's compare-and-set is the only commit point; a second redemption, concurrent or later, is the 404 and writes nothing. |
| Lead escalation | The entry is exactly what an email invitation gives (no `lead`, no role, the maker's own team); it lapses with the maker's lead. |
| Membership or existence oracle | One 404 for every refusal; the token names no team; no GET reveals a link; revoke has one answer; the list shows no redeemer. |
| Token in logs, referrers or storage | Token in the URL fragment and a POST body only; the `/join` page clears the fragment with `history.replaceState`, keeps the token in `sessionStorage` only across a sign-in redirect and deletes it after the answer, and sends `Referrer-Policy: no-referrer`. The API never logs bodies; only the digest is stored. |
| Link previews and CSRF | A GET consumes nothing; redemption is an authenticated POST with a bearer ID token (no cookies). |
| Key misuse | A dedicated key (never `TILO_LINK_SIGNING_KEY`); rotating `kid` invalidates every link signed by the old key. |
| Flooding | `write_limit`, 10 pending links per team, the 7-day life, and the redeemer's 8-entry limit. |

## Consequences
- `packages/contracts-py` and `packages/contracts-ts` gain `TeamInviteLink` and three event data models;
  `apps/web/src/world/registry.generated.ts` gains three types.
- Fixtures: `contracts/fixtures/team_invite_link/{valid,invalid}/` (shape) and `crossref/{valid,invalid}/` (53 cases);
  the reference check is `tests/contracts/_invite_link_lib.py`; `_teams_lib` follows the amended PE-37.
- **For the builders** (tickets in `agy-bridge/tasks/INVITE-LINK-TICKETS.md`): `tilo_people.teams` gains
  `create_link`, `revoke_link` and `redeem_link` and the amended `remove_member`, and its suite runs
  `team_invite_link/crossref/`; tilo-api gains the routes, the signer, the store and the events; the web gains the
  Team page's link panel and the `/join` page. Security review before merge.
- Deploy needs the new secret on tilo-api (BQ-INVL-1); until then making and redeeming answer 503 and nothing else
  changes.

## Alternatives considered
- **An unsigned random token** (as FR-HIL-12 share links): equally unguessable, but the owner asked for signed links,
  and a key allows mass revocation by rotation.
- **`invite_link_id` on the membership** (the proposal's `person` 1.2.0): the entry is already fully described by
  existing fields and the link record keeps the provenance; it would add a schema bump for no new check.
- **Org and team claims in the token**: they would show the team to anyone holding the link and duplicate the record.
- **A configurable life (1 hour to 30 days)**: more input to validate; nothing in the request needs it yet.
