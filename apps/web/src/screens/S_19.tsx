// S-19 Connections (PRD 18.3, 12.1): every connection the world has, its state in words, the gates
// that guard what it may do and the access still waiting for consent. Islands and gates come from
// client.getLayout, consent cards from client.listCards. Connect and disconnect are placeholders.
// Access copy follows PRD 18.4: you sign in with the provider and Tilo never sees your password.
// No design export lists connections (design/source/INDEX.md, S-19): cards and rows after
// "Tilo Team.dc.html", neutral role tokens.
import { useClient } from "../api/ClientProvider";
import { FIXTURE_WORLD_ID as worldId } from "../api/fixtures/derived";
import { AppLink } from "./AppLink";
import { Loaded } from "./FlowShell";
import { Placeholder } from "./Placeholder";
import { Chip, Page, Row, Section, Stats, words } from "./kit";
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
  const [layout, retryLayout] = useRemote("load the connections", () => client.getLayout(worldId));
  const [cards, retryCards] = useRemote("load the consent requests", () =>
    client.listCards(worldId),
  );
  const islands = layout.status === "ready" ? layout.value.semantic.islands : [];
  const consent = cards.status === "ready" ? cards.value.filter((c) => c.consent !== null) : [];
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
          ["Waiting for consent", cards.status === "ready" ? consent.length : "-"],
        ]}
      />
      <Section title="In this world" reserve={9}>
        <Loaded
          what="the connections"
          remote={layout}
          retry={retryLayout}
          isEmpty={(l) => l.semantic.islands.length === 0}
        >
          {(l) => (
            <ul className="rows" data-testid="connection-list">
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
      <Section title="Waiting for your consent" reserve={5}>
        <Loaded what="the consent requests" remote={cards} retry={retryCards} isEmpty={() => false}>
          {() =>
            consent.length === 0 ? (
              <p className="empty-note">No access request is waiting.</p>
            ) : (
              <ul className="rows" data-testid="consent-list">
                {consent.map((c) => (
                  <Row
                    key={`${c.id}:${c.rung}:${c.what_happened}`}
                    name={words(c.consent?.connector ?? "")}
                    sub={c.consent?.scopes.join("; ")}
                    state={<Chip tone="needs">Waiting</Chip>}
                  >
                    <AppLink to="/needs-you/consent" className="pill">
                      Review
                    </AppLink>
                  </Row>
                ))}
              </ul>
            )
          }
        </Loaded>
      </Section>
    </Page>
  );
}
