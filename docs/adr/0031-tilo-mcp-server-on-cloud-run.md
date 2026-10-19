# ADR-0031: Tilo as an MCP server on Cloud Run

- Status: Accepted (user approved 8 Oct 2026). The supervisor asked for this design on the user's behalf;
  the user approved it in the supervisor chat. Open questions keep their stated defaults.
- Deciders: user (approval; turning the server on; which clients; the new public routes), architect (design)
- Requirement: none in the PRD (an MCP *client* is FR-CON-12; a server is new, at the user's request of 8 Oct
  2026). It touches SEC-03, SEC-07, SEC-10, SEC-11, SEC-12, SEC-15, SEC-16; PRD 10.4 (tiers), 16.3; OB-01;
  FR-INT-01 to -05; HR-1, HR-7; ADR-0018, ADR-0019 (CH-RM).

## Context
1. People want to reach their Tilo work from the assistants they already use (Claude, Gemini): see their
   worlds, read finished deliverables, answer Tilo's questions and start work, without opening Tilo.
2. MCP (Model Context Protocol) is the common way to do that. A remote MCP server speaks JSON-RPC over
   "streamable HTTP". Its authorization specification makes the server an OAuth 2.1 resource server: it
   publishes protected-resource metadata (RFC 9728), clients use authorization code with PKCE and a resource
   indicator (RFC 8707), and the server accepts only tokens issued for itself (no token passthrough).
3. Tilo today: tilo-api (Cloud Run, public ingress, min 0, max 3) authenticates people with Firebase ID tokens,
   puts App Check (SEC-10) and the access declaration gate (SEC-15) in front of every route except an exact
   `PUBLIC_ROUTES` list, and runs a world's run and `CardStore` in its own process (ADR-0026 is still
   Proposed). `config/mcp.yaml` is the allowlist of servers Tilo's MCP *client* may call (FR-CON-12). It is
   empty, and it has nothing to do with clients calling Tilo.
4. App Check cannot apply: it attests Tilo's own web app, and Claude or Gemini are not that app.

## Decision
1. **A route inside tilo-api, not a new service (for now).** Mount the MCP endpoint at `POST /mcp` and the OAuth
   endpoints in tilo-api. Reasons: a run's cards and its intake live in tilo-api's process, so only tilo-api can
   call the same `CardStore.answer` and `submit_intake` the web uses (a separate service would need a
   delegated-principal call into tilo-api, a new trust boundary). It adds no service account, no new ingress
   and no idle cost. Split into a `tilo-mcp` service once a durable world and card store lands (ADR-0026),
   if load or isolation then calls for it.
2. **Protocol: small and stateless.** Streamable HTTP in stateless JSON mode: each `POST /mcp` carries one
   JSON-RPC request and gets one `application/json` answer, with no SSE stream, no session id and no
   server-initiated messages (`GET /mcp` is 405). Methods: `initialize`, `ping`, `tools/list`, `tools/call`.
   There are no resources, prompts, sampling or elicitation (sampling would make Tilo call the client's model).
   The `Origin` header, when present, must be allowlisted, or the answer is 403 (DNS rebinding). Use the
   official MCP Python SDK (MIT; record it in `docs/licences.md`) for the protocol layer.
3. **Seven tools, one contract (`contracts/mcp_tools.schema.json`).** Each tool maps to code the web already runs
   (MC-05):

   | Tool | Scope | Same path as | Result |
   | --- | --- | --- | --- |
   | `list_worlds` | `tilo.read` | `GET /worlds` (S-14, owner scope) | `world_row`s, newest first, at most 50 |
   | `get_world` | `tilo.read` | the owner's `GET /worlds/{id}/events` view | row, open cards, credits used, newest 20 Story lines |
   | `list_artifacts` | `tilo.read` | artifact store `head` through the Scope | recorded, clean versions |
   | `read_artifact` | `tilo.read` | artifact store `read` (hash-checked, AR-01) | text for Markdown, CSV and JSON up to 256 KiB, else withheld |
   | `list_cards` | `tilo.read` | the card feed | open cards with what each may answer here |
   | `answer_card` | `tilo.write` | `CardStore.answer(channel="mcp")` | `needs_you` cards only |
   | `start_run` | `tilo.write` | `submit_intake(channel="mcp")` | the world, waiting for the person in Tilo |

   Read-only by default: the consent screen grants `tilo.read`, and `tilo.write` is a separate, off-by-default
   switch per client. The person's worlds only (MC-04): a teammate's or a shared world is not offered in this
   version.
4. **No authorisation over MCP, whatever the tier (MC-09, MC-10).** The client is a model acting between the
   person and Tilo, and a model never decides authorisation. So channel `mcp` answers plain questions
   (`needs_you`) only, the way email does since CH-RM. It never opens a gate (T2 or T3), never gives a
   consent, never answers a meeting card, and never counts as an L2 instruction (OB-01 lists only `web` and
   `mobile_web`). `start_run` runs intake only; answering intake questions and approving an approach (the
   spend) happen in Tilo. A gate's `hold` is not offered either: it writes nothing (CR-07). An MCP answer is
   not saved as a reusable Decision.
5. **Auth: Tilo's own small OAuth 2.1 authorization server, with consent in the signed-in web app.**
   - Discovery: `GET /.well-known/oauth-protected-resource` (RFC 9728) and
     `GET /.well-known/oauth-authorization-server` (RFC 8414). A missing or bad token gets 401 with
     `WWW-Authenticate: Bearer resource_metadata="<url>"`.
   - `GET /oauth/authorize`: the client must be allowlisted in `config/mcp_server.yaml` with an exact
     redirect URI (a loopback `http://127.0.0.1` port range only for a CLI client listed as such). It must
     send PKCE `S256`, a `state` and `resource` equal to the configured MCP URL. tilo-api stores a pending
     request (10 minutes) and redirects to the web app's consent screen.
   - **Consent screen** (`/connect/mcp`, web): signed in with Firebase, behind App Check and the access
     declaration. It shows the client's configured name and what it may do (read; optionally answer questions
     and start work). Approve or deny goes to `POST /v1/mcp/requests/{id}/approve|deny`, a normal signed-in
     route. Approval writes `mcp.granted` and returns the client's redirect with a one-time code (60 seconds,
     bound to the client, redirect URI, PKCE challenge and person).
   - `POST /oauth/token`: code plus verifier gives an access token (opaque, `tmcp_` prefix, 1 hour) and a
     rotating refresh token (30 days). Reusing a refresh token revokes the grant (`mcp.revoked`).
     `POST /oauth/revoke` (RFC 7009) lets a client end it. Tokens are stored only as SHA-256 hashes in
     Firestore (`mcp_grants`, `mcp_tokens`).
   - Tilo never sees a password; Firebase signs the person in. Firebase ID tokens are accepted only on the
     consent routes, never as MCP tokens (MC-01).
   - Clients: a pre-registered allowlist only (`clients: []` until the user adds Claude or Gemini with their
     published redirect URIs). Dynamic client registration stays off (BQ-MCP-2).
6. **The App Check substitute, stated plainly.** App Check proves "this is Tilo's web app". Over MCP that proof is
   replaced by six checks:
   - an allowlisted client with exact redirect URIs;
   - PKCE;
   - consent given in the App-Check-protected, signed-in web app;
   - short-lived, audience-bound, hashed, revocable tokens;
   - read-only by default, with no authorisation possible;
   - per-grant rate limits and the SEC-16 spend caps.

   What it does not prove: that a call reflects the person's intent at that moment (an injected instruction in
   the client's context could call a write tool). That is why nothing over MCP authorises, and why write tools
   are off by default and bounded.
7. **New public routes (an owner decision).** `POST /mcp`, the two `/.well-known/` documents, `GET /oauth/authorize`,
   `POST /oauth/token` and `POST /oauth/revoke` join `PUBLIC_ROUTES` (`access.py`) and App Check's `EXEMPT_ROUTES`,
   like `/internal/schedules/tick`. Each checks its own caller: `/mcp` the token (MC-01) and then the person's
   access declaration (MC-02); the OAuth routes the client and PKCE. The test that pins `PUBLIC_ROUTES` changes
   with the user's approval of this ADR.
8. **Audit (MC-12), every call an event with authz.** A new `mcp` event family, added by ticket MCP-a at the
   next free registry minor:
   - `mcp.granted`: side effect, `authz_by: [person]`. The person let a client use Tilo.
   - `mcp.called`: side effect, `authz_by: [person]`, `authz` equal to the grant's. One per authenticated call,
     refused ones included. Data: grant, client, tool, outcome, refusal code, ids touched; never argument text,
     content or a token.
   - `mcp.revoked`: authz null; the withdrawal, by the person, the client, expiry or refresh reuse.

   All three go to the person's Desk world (PE-12), so the Trace shows who used Tilo from where. They mark data
   leaving Tilo to a client the person chose, which is the same reason `data.transfer` carries the person's
   consent for reads. Each needs its world effect, HUD effect, Story line, Trace row, data schema and fixture,
   and `event.schema.json`'s side-effect list grows by two.
9. **Channel `mcp` (ticket MCP-a).** `common.schema.json` `channel` gains `mcp` (minor), as `schedule` was added
   (1.4.0). It is a way in, never an owner instruction or a person's approval. A card rule makes it never
   appear on gate, consent or meeting cards, only on `needs_you` cards, and `world.requested` may carry it.
   `CardStore._ANSWER_CHANNELS` gains `mcp` with email's "`needs_you` only" line.
10. **Fit with the MCP client.** Two files, two directions: `config/mcp.yaml` stays the allowlist of servers Tilo
    calls (FR-CON-12, still empty), and the new loader-checked `config/mcp_server.yaml` holds the server:
    `enabled: false`, `resource: null` (the public MCP URL, set at deploy), `clients: []`,
    `token_ttl_s: 3600`, `refresh_ttl_days: 30`,
    `limits: {calls_per_minute: 60, writes_per_minute: 10, start_run_per_day: 5}`,
    `read_artifact_max_bytes: 262144`. The client's loader refuses any endpoint on Tilo's own hosts, so Tilo
    never calls itself. In the world metaphor (rail = MCP), the Desk world shows the line that `mcp.granted`
    opens.

## Security
- **Cross-user:** owner scope on every tool; another person's ids get `not_found`, byte-equal to a missing one.
  No argument names a user, role, org or channel (closed schemas, fixtures `answer_card_names_a_user`,
  `answer_card_sets_its_channel`).
- **Tokens:** opaque, hashed, prefixed for the secret scanner, audience-checked, never logged, never in events,
  revocable from Settings in one tap. A stolen access token lasts at most an hour and reads at most what the
  person could read.
- **Injection both ways:** inbound arguments are typed and closed. Outbound artifact text may carry an
  injection aimed at the client's model, so it is marked as data. The worst a hijacked client can do is answer
  a plain question or start an intake within caps; it cannot send, share, connect or spend past intake.
- **Data leaving Tilo:** only to a client the person allowlisted and consented to, only their own worlds, only
  clean text versions. Every call is in the Trace. Personal-class content is served to its owner like on the
  web (BQ-MCP-5).
- **Abuse and cost:** per-grant and per-person limits, SEC-16 caps, intake's own safety screen, no model call on
  any read tool.

## Alternatives considered
- *A separate `tilo-mcp` Cloud Run service now:* cleaner isolation, but it must reach the in-process `CardStore`
  and intake through tilo-api with a delegated principal (a service that may speak for any person), or
  duplicate them (a bypass). Revisit after ADR-0026.
- *Firebase ID tokens as MCP tokens:* their audience is the Firebase project, so a token leaked from a client
  would work on every tilo-api route. They have no per-client scope or consent, last an hour with no refresh
  for a third party, and break the MCP rule that tokens be issued for the MCP server.
- *Google Identity Platform or another hosted authorization server:* none in the stack issues tokens to
  third-party clients with per-client consent for our resource. Adding one is a new vendor; the user can
  choose it later (BQ-MCP-2).
- *Let MCP approve T2 gates with a step-up:* possible later (for example a push to Tilo that the person taps),
  but that tap would be the authorisation, so the gate stays in Tilo (BQ-MCP-4).
- *Expose everything as MCP resources:* tools with closed inputs and outputs are easier to scope, limit and
  audit.

## Consequences
- Tickets (tests first; reviewers in brackets):
  - **MCP-a** (architect): `common` channel `mcp`; the card rule; the `mcp` event family (three types, data
    schemas, fixtures, the `event.schema.json` side-effect list); regenerated types and the web registry; the
    next free registry and `common` minors at that time.
  - **MCP-b** (reach-builder; security-reviewer): the authorization server, discovery documents, grant and token
    store, PKCE, audience, rotation and reuse detection, revocation, `config/mcp_server.yaml` and its loader,
    the `PUBLIC_ROUTES`/`EXEMPT_ROUTES` entries, the consent API routes.
  - **MCP-c** (reach-builder or intelligence-builder; security-reviewer, cost-reviewer): `POST /mcp` with the SDK in
    stateless JSON mode, the seven tools on the web's code paths, MC-01 to MC-12, limits, the `mcp.called`
    audit.
  - **MCP-d** (world-builder; design-critic): the consent screen and Settings "Connected assistants" (list,
    write switch, revoke).
  - **MCP-e** (qa-breaker; the user): conformance against a local server with an MCP inspector tool, then the
    user's live step: set `enabled: true`, add a client, connect it to `tilo-dev`, and run one read and one
    refused gate answer.
- Every ticket waits for this ADR's approval and for MCP-a's contracts.
- Open points: BQ-MCP-1 to BQ-MCP-8 in `docs/open-questions.md`.
