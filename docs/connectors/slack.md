# Slack preparation (PREP-SLACK-1, FR-UX-17)

This connector is inert. `config/slack.yaml` is a standalone declaration; its posting
and listing actions are absent from `config/connectors.yaml` and MCP. The inherited
`slack` catalogue placeholder (read_slack, empty scopes) is preserved unchanged.
No app route or production factory imports the new adapter.
Status without owner configuration: "Needs the workspace owner's Slack app".

The prepared adapter lists public channels and posts approved plain text to a chosen
public channel where the bot has been invited. Each post needs the existing outbox
and deterministic T3 approval. Bodies use the shared secret redactor; mention parsing,
Markdown and unfurls are disabled. The stored artifact's world and hash are checked.
The outbox id is sent as `client_msg_id`. A ledger reservation precedes the HTTP call;
an ambiguous response fails closed for a person to inspect, without automatic resend.
The in-memory ledger and injected transport are preparation seams, not production wiring.

## Owner activation steps and outstanding holds

1. Create an app in the owner's Slack workspace using Slack's app dashboard.
   Request bot scopes `channels:read` and `chat:write`; no history, private channels,
   direct messages, user impersonation or `chat:write.public` is requested.
2. Register the redirect URI **only after** the provider-specific OAuth callback is
   implemented and reviewed. The existing connection consent seam is Google-specific;
   this prep does not invent an operational Slack callback URL. Its future URI must
   be the deployed connectors base plus the approved Slack callback path, exactly
   matching the app setting. Activation is BLOCKED on this route/consent seam.
3. Store credentials in Secret Manager under names `SLACK_OAUTH_CLIENT_ID` and
   `SLACK_OAUTH_CLIENT_SECRET`; never put values in config, docs or fixtures. Implement
   owner-bound Slack OAuth exchange, encrypted bot-token storage and disconnect/revoke
   through the broker before enabling. Configure transport with bearer headers to
   Slack Web API only, bounded timeouts, no hidden post retries and redacted errors.
4. Bind a durable atomic reservation ledger shared across workers and restarts and
   bind mock/real adapters in the connector factory. Run registry-wide activation
   invariants and the recorded plan/connect-route tests before catalogue promotion.
   Invite the bot to the chosen channel. No activation has been performed here.
5. After those holds and supervisor gate approval, the catalogue move is one line:
   `python -c "from pathlib import Path; import yaml; p=Path('config/connectors.yaml'); rows=yaml.safe_load(p.read_text()); new=yaml.safe_load(Path('config/slack.yaml').read_text()); p.write_text(yaml.safe_dump([r for r in rows if r['id']!='slack']+new, sort_keys=False))"`
   This replaces the existing reserved Slack entry; appending would create a duplicate id.
   Then enable the factory explicitly; its `enabled` default remains false.

References checked 14 October 2026: [channel listing](https://docs.slack.dev/reference/methods/conversations.list/)
and [posting](https://docs.slack.dev/reference/methods/chat.postMessage/).
Private-channel and DM support require a separate scoped review. Slack card delivery
and signed approval links are separate PREP-SLACK-2 work.
