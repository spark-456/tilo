// S-15 Autonomy (PRD 18.3, 10.4): levels, the gates that stand in for policies, the kill switch and
// the Autonomy log. The log is every recorded event that carries `authz` (UX-9); an action a policy
// authorised wears the policy colour and a "Policy" stamp (PRD 18.6). Policies themselves are not
// served by the fixture client, so none is listed. Rows after design/source "Tilo Team.dc.html"
// ("When Tilo stops and asks", rules only); the rest uses neutral role tokens.
import { useClient } from "../api/ClientProvider";
import { waitingForYou } from "../world/runLog";
import { Loaded } from "./FlowShell";
import { Placeholder } from "./Placeholder";
import { findItem } from "./S_05";
import { Chip, Page, Row, Section, Soon, Stats, authzText, useFixtureRun, words } from "./kit";
import { useRemote } from "./remote";

// PRD 10.4 levels.
const LEVELS: ReadonlyArray<readonly [string, string, string]> = [
  ["L0", "Observe", "Agents may only draft; nothing leaves Tilo."],
  ["L1", "Ask each time", "Every side effect waits at a gate. This is the default."],
  ["L2", "Instruction is approval", "Acts on your explicit instruction, with an undo window."],
  ["L3", "Standing rules", "Pre-authorised actions run within limits and appear in a digest."],
];

export function S_15() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [layout, retry] = useRemote("load the gates", () => client.getLayout(worldId));
  const log = events.filter((e) => e.authz !== null);
  return (
    <Page
      testid="autonomy"
      title="Autonomy"
      sub="Decide what Tilo may do on its own. Every action it takes under a rule is listed here."
    >
      <Stats
        items={[
          ["Authorised actions", log.length],
          ["Waiting for you", waitingForYou(events)],
        ]}
      />
      <Section
        title="Stop all autopilot"
        note="Sets every rule to level L1 at once, so everything waits for you. Pause all also stops the agents."
      >
        <Placeholder label="Stop all autopilot" compact />
      </Section>
      <Section title="Levels">
        <ul className="rows">
          {LEVELS.map(([id, name, what]) => (
            <Row
              key={id}
              name={name}
              sub={what}
              state={<Chip tone={id === "L1" ? "done" : "fyi"}>{id}</Chip>}
            />
          ))}
        </ul>
      </Section>
      <Section title="Rules" note="A gate with no rule waits for a person." reserve={7}>
        <Soon labels={["New rule"]} />
        <Loaded what="the gates" remote={layout} retry={retry} isEmpty={() => false}>
          {(l) => (
            <ul className="rows" data-testid="gates">
              {l.semantic.gates.map((g) => (
                <Row
                  key={g.id}
                  name={words(g.guards)}
                  sub={`${findItem(l, g.between[0])?.name ?? "A building"} to ${l.semantic.islands.find((i) => i.id === g.between[1])?.name ?? "a connection"}`}
                  state={
                    g.policy_ref ? (
                      <Chip tone="policy">Policy: runs on its own</Chip>
                    ) : (
                      <Chip tone="needs">Waits for you</Chip>
                    )
                  }
                />
              ))}
            </ul>
          )}
        </Loaded>
      </Section>
      <Section
        title="Autonomy log"
        note="Every action with an authoriser, as it was recorded."
        reserve={[14, 26]}
      >
        {log.length === 0 ? (
          <p className="empty-note">No authorised action has been recorded yet.</p>
        ) : (
          <ul className="rows" data-testid="autonomy-log">
            {log.map((e) => (
              <Row
                key={e.seq}
                name={e.summary}
                sub={e.authz ? `Authorised by ${authzText(e.authz).toLowerCase()}` : undefined}
                state={
                  <Chip tone={e.authz?.by === "policy" ? "policy" : "done"}>
                    {e.authz?.by === "policy" ? "Policy stamp" : "Approved"}
                  </Chip>
                }
              >
                {e.type === "data.transfer" && (
                  <span className="soon-row">
                    <Placeholder label="Undo" compact />
                    <Placeholder label="Report" compact />
                  </span>
                )}
              </Row>
            ))}
          </ul>
        )}
      </Section>
    </Page>
  );
}
