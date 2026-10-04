// S-19 Connections (PRD 18.3, 12.1): every connection the world has, its state in words, the gates
// that guard what it may do and the access still waiting for consent. Islands and gates come from
// client.getLayout (the world's starting state); consent requests come only from this run's
// connection.requested events that no connection.consented or connection.revoked has answered.
// Connect and disconnect are placeholders. Access copy follows PRD 18.4: you sign in with the
// provider and Tilo never sees your password. No design export lists connections
// (design/source/INDEX.md, S-19): cards and rows after "Tilo Team.dc.html", neutral role tokens.
import { useClient } from "../api/ClientProvider";
import { AppLink } from "./AppLink";
import { Loaded } from "./FlowShell";
import { Placeholder } from "./Placeholder";
import { Chip, Page, Row, Section, Stats, field, nameOf, useFixtureRun, words } from "./kit";
import { useRemote } from "./remote";

const STATE = {
  locked: ["Not connected", "blocked"],
  requested: ["Waiting for your consent", "needs"],
  connected: ["Connected", "done"],
  failed: ["Access lost", "blocked"],
} as const;
const KIND = {
  api: "Sign-in connection",
  mcp: "Agent protocol (MCP)",
  browser: "Cloud browser",
  channel: "Channel",
} as const;

export function S_19() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [layout, retry] = useRemote("load the connections", (signal) =>
    client.getLayout(worldId, signal),
  );
  // A request is answered by a consent for its card, or by a later revocation of its connector
  // (connection.revoked carries the connector, not a card).
  const consent = events.filter(
    (e) =>
      e.type === "connection.requested" &&
      !events.some(
        (x) =>
          (x.type === "connection.consented" && field(x, "card_id") === field(e, "card_id")) ||
          (x.type === "connection.revoked" &&
            x.seq > e.seq &&
            field(x, "connector") === field(e, "connector")),
      ),
  );
  const islands = layout.status === "ready" ? layout.value.semantic.islands : [];
  return (
    <Page
      testid="connections"
      title="Connections"
      sub="The places Tilo can reach for you. You sign in with the provider; Tilo never sees your password."
    >
      <Stats
        items={[
          [
            "Connected",
            layout.status === "ready" ? islands.filter((i) => i.state === "connected").length : "-",
          ],
          ["Waiting for consent", consent.length],
        ]}
      />
      <Section
        title="In this world"
        note="Where this world starts, from its layout."
        reserve={[8, 12]}
      >
        <Loaded
          what="the connections"
          remote={layout}
          retry={retry}
          isEmpty={(l) => l.semantic.islands.length === 0}
        >
          {(l) => (
            <ul className="blist" data-testid="connection-list">
              {l.semantic.islands.map((i) => {
                const gates = l.semantic.gates.filter((g) => g.between[1] === i.id);
                return (
                  <Row
                    key={i.id}
                    name={i.name}
                    sub={[
                      KIND[i.conn],
                      ...gates.map((g) => `${words(g.guards)} needs a gate`),
                    ].join(" · ")}
                    state={<Chip tone={STATE[i.state][1]}>{STATE[i.state][0]}</Chip>}
                  >
                    <Placeholder
                      label={i.state === "connected" ? `Disconnect ${i.name}` : `Connect ${i.name}`}
                      compact
                    />
                  </Row>
                );
              })}
            </ul>
          )}
        </Loaded>
      </Section>
      <Section
        title="Waiting for your consent"
        note="Each request lists exactly what it may do. You sign in with the provider; Tilo never sees your password."
        reserve={[4, 6]}
      >
        {consent.length === 0 ? (
          <p className="empty-note" data-testid="consent-empty">
            No access request is waiting.
          </p>
        ) : (
          <ul className="blist" data-testid="consent-list">
            {consent.map((e) => (
              <Row
                key={e.seq}
                name={nameOf(String(field(e, "connector")))}
                sub={e.summary}
                state={<Chip tone="needs">Waiting</Chip>}
              >
                <AppLink
                  to="/needs-you/consent"
                  className="pill"
                  aria-label={`Review: ${e.summary}`}
                >
                  Review
                </AppLink>
              </Row>
            ))}
          </ul>
        )}
      </Section>
    </Page>
  );
}
