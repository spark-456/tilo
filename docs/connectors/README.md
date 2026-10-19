# Connector status and owner activation

Submission notes, 14 October 2026. The public web site is reachable; this docs-only
check proves no authenticated connector operation. A tile, adapter, prepared card
or passing fake test does not establish live availability or delivery.

| Integration | Evidence and current limit |
| --- | --- |
| Gmail, Drive, Calendar | Repository adapters and OAuth/outbox design exist. Connection and each live capability require configured owner consent and observed provider results. |
| Meeting host | Broker design exists; keep the not-connected state until configuration and owner acceptance establish availability. |
| Slack cards | Offline card preparation `00ea0d39`; no live Slack send established. |
| Teams cards | Offline Adaptive Card preparation `f57cec5b`; no live Teams send established. |
| Outlook cards | Offline card preparation `5ed57327`; no live Outlook send established. |
| Partner tiles | Inert UI preparation `143f1916`; displaying a tile does not connect an account. |
| Canva | Separate declaration in `config/canva.yaml`; owner app registration and confirmed scopes/provider behavior remain prerequisites. No live design/export/share established here. |
| Lovable | The catalogue's `build_handoff` is a prompt the person sends manually. The separate [MCP preparation](lovable-mcp.md) uses synthetic fixture metadata and remains blocked. |

These preparation commits are evidence of offline work on separate branches, not
a statement that they are integrated into candidate `182beac2` or the hosted build.
Integration is owned by the assigned integration lane; publication and activation
require their own evidence and authorisation.

## Owner requirements and runbooks

- Google OAuth, token store/KMS, connector setup and meeting-host acceptance:
  [deployment runbook](../deploy-dev.md) and
  [ADR-0035](../adr/0035-live-connectors-oauth-outbox-adapters.md).
- Connector state and capability reads:
  [ADR-0032a](../adr/0032a-connection-views.md).
- Model keys and owner controls: [BYOK runbook](../byok.md).
- Canva uncertainty, declaration and app requirements:
  [open questions BQ-CON19-1/2](../open-questions.md) and `config/canva.yaml`.
- Lovable MCP: verified endpoint/tools/auth metadata, verbatim-arguments approval,
  durable call ledger and production transport/egress proofs are still required;
  [the preparation document](lovable-mcp.md) records each blocker.

Slack, Teams and Outlook require reviewed provider-specific app/consent, verified
capabilities and transport, policy/outbox enforcement and owner acceptance before
any live delivery claim. This index supplies no activation permission or credentials.
