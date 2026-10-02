// S-13 Library and Memory Vault (PRD 18.3, 13.1): what Tilo has made and what it remembers.
// Deliverables come from client.getDelivery; memory from the recorded memory.hit and memory.saved
// events (none in the fixture run, so the vault says so). No design export covers this screen:
// cards and rows after "Tilo Worlds.dc.html", neutral role tokens (design/source/INDEX.md, S-13).
import { useClient } from "../api/ClientProvider";
import { AppLink } from "./AppLink";
import { Loaded } from "./FlowShell";
import { Page, Row, Section, Soon, Stats, useFixtureRun } from "./kit";
import { useRemote } from "./remote";

// PRD 13.1 memory layers: what each holds and when it may be reused.
const LAYERS: ReadonlyArray<readonly [string, string]> = [
  ["Working memory", "The run's plan, artifacts and notes. This run only."],
  ["Result cache", "Tool results and extracted tables. Fresh for 7 days, never email bodies."],
  ["Artifact memory", "Past deliverables. Offered as a starting point, never silently reused."],
  ["Decisions", "Answers from you and Team Leads. They answer repeat questions."],
  ["Preferences", "Your settings and triage corrections. Applied in planning and drafting."],
  ["Skills", "Expert skills and versions. Loaded when a task needs them."],
];

export function S_13() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [delivery, retry] = useRemote("load the library", () => client.getDelivery(worldId));
  const count = (type: string) => events.filter((e) => e.type === type).length;
  const made = delivery.status === "ready" ? delivery.value.artifacts.length : "-";
  return (
    <Page
      testid="library"
      title="Library and Memory Vault"
      sub="What Tilo has made for you, and what it remembers for next time."
    >
      <Soon labels={["Search the library", "Forget a memory item"]} />
      <Stats
        items={[
          ["Deliverables", made],
          ["Memory reuses", count("memory.hit")],
          ["Items remembered", count("memory.saved")],
        ]}
      />
      <Section title="Library" note="Deliverables Tilo has finished." reserve={[4, 5]}>
        <Loaded
          what="the library"
          remote={delivery}
          retry={retry}
          isEmpty={(d) => d.artifacts.length === 0}
        >
          {(d) => (
            <ul className="rows">
              {d.artifacts.map((a) => (
                <Row key={a.id} name={a.title} sub={`${a.kind}, version ${a.version}`}>
                  <AppLink to="/library/artifacts" className="pill">
                    Version history
                  </AppLink>
                </Row>
              ))}
            </ul>
          )}
        </Loaded>
      </Section>
      <Section title="Memory Vault" note="Tilo reuses a result only after a check accepts it.">
        {count("memory.hit") + count("memory.saved") === 0 && (
          <p className="empty-note" data-testid="memory-empty">
            No memory event has been recorded for this run.
          </p>
        )}
        <ul className="rows">
          {LAYERS.map(([layer, what]) => (
            <Row key={layer} name={layer} sub={what} />
          ))}
        </ul>
      </Section>
    </Page>
  );
}
