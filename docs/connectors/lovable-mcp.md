# Lovable MCP preparation (FR-CON-18, FR-CON-12)

Status: Needs the workspace owner's Lovable app. Inert preparation only.
`config/mcp.yaml` remains empty. No connector catalogue, route, flag or transport
is installed by this preparation. There are no credentials or secret values here.

The offline declaration is
`services/connectors/tests/fixtures/lovable-mcp.yaml`. Its `.example` endpoint and
`build_handoff` tool name are synthetic test inputs, **not verified vendor metadata**.
It maps a build handoff to the existing `build_handoff` action: T3, side effect,
person approval through the policy engine and outbox only. No read tools are
declared: a future verified read tool requires an existing matching T1 policy action;
unlisted actions resolve to T3 and must never be labelled as reads.

## Existing checks exercised with fakes

The candidate loads through `load_allowlist` with the shipped risk table and
connector reservations. An injected fake transport receives the original arguments
only after a person-authorized outbox entry dispatches; direct T3 reads and missing
outbox grants are refused. Repeated dispatch does not send again. Private literal
endpoints are rejected by the existing lexical endpoint validator.

These checks prove the current validation and fake dispatch path, not #415 readiness.

BLOCKED: #415 verbatim-arguments approval card. No MCP-specific card renderer is
wired to display the exact `mcp_call.arguments` that `McpAdapter._arguments` sends;
an outbox test alone cannot prove what a person saw or approved.

BLOCKED: #415 durable call ledger. `InMemoryMcpCallLedger` and `_LEDGERS` in
`services/connectors/src/tilo_connectors/mcp.py` are process memory; restart-safe
atomic begin/finish storage and uncertainty/replay proof are missing.

BLOCKED: #415 transport and egress/DNS rebinding. `McpTransport` is an injected
protocol; `_public_endpoint` checks syntax and literal addresses only. Production
resolved-IP validation, connection pinning and redirect/rebinding checks are absent.

BLOCKED: owner-provided verified endpoint, tool names/schemas, least-privilege auth
and secret NAMES. The delivered ticket supplies none; the synthetic declaration
must not be represented as an activation-ready vendor allowlist.

Activation after all blockers have evidence and reviewer approval: replace the
synthetic values with owner-verified metadata, then add the reviewed entry to
`config/mcp.yaml` servers. This step is held for a later authorized gate.
