// S-15 Autonomy (PRD 18.3, 10.4): levels, the gates that stand in for policies, the kill switch and
// the Autonomy log. The log is every recorded event that carries `authz` (UX-9); each row says who
// authorised it and when (authz.at) and links to its authorisation in the Trace (HR-7). An action a
// policy authorised wears the policy colour and a "Policy" stamp (PRD 18.6). Policies themselves
// are not served by the fixture client, so none is listed. Rows after design/source "Tilo Team.dc.html".
import type { Event } from "@tilo/contracts";
import { useClient } from "../api/ClientProvider";
import { waitingForYou } from "../world/runLog";
import { AppLink } from "./AppLink";
import { Loaded } from "./FlowShell";
import { Placeholder } from "./Placeholder";
import { findItem } from "./S_05";
import {
  Chip,
  Page,
  Row,
  Section,
  Soon,
  Stats,
  authzText,
  field,
  stamp,
  useFixtureRun,
  words,
} from "./kit";
import { useRemote } from "./remote";

// PRD 10.4 levels.
const LEVELS: ReadonlyArray<readonly [string, string, string]> = [
  ["L0", "Observe", "Agents may only draft; nothing leaves Tilo."],
  ["L1", "Ask each time", "Every side effect waits at a gate. This is the default."],
  ["L2", "Instruction is approval", "Acts on your explicit instruction, with an undo window."],
  ["L3", "Standing rules", "Pre-authorised actions run within limits and appear in a digest."],
];

/** PRD 10.4: every action starts here. No policy is served in this build, so it is the one level
 * that can be named; it is marked by a tick and the word "Default", not by colour. */
const DEFAULT_LEVEL = "L1";

/** The approval that released an outgoing action (same outbox entry), else the event itself. */
const authorisation = (events: readonly Event[], e: Event): Event =>
  events.find(
    (x) =>
      x.type === "approval.resolved" &&
      field(x, "outbox_id") != null &&
      field(x, "outbox_id") === field(e, "outbox_id"),
  ) ?? e;

export function S_15() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [layout, retry] = useRemote("load the gates", (signal) =>
    client.getLayout(worldId, signal),
  );
  const log = events.filter((e) => e.authz !== null);
  const trace = `/world/${encodeURIComponent(worldId)}/trace`;
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
      <Section
        title="Levels"
        note="Every action starts at level L1: it waits for you until you say otherwise."
      >
        <ul className="blist">
          {LEVELS.map(([id, name, what]) => (
            <Row
              key={id}
              name={name}
              sub={what}
              state={
                id === DEFAULT_LEVEL ? (
                  <Chip tone="done">✓ {id} · Default</Chip>
                ) : (
                  <Chip tone="none">{id}</Chip>
                )
              }
            />
          ))}
        </ul>
      </Section>
      <Section
        title="Rules"
        note="A gate with no rule waits for a person."
        reserve={5}
        action={<Soon labels={["New rule"]} />}
      >
        <Loaded what="the gates" remote={layout} retry={retry} isEmpty={() => false}>
          {(l) => (
            <ul className="blist" data-testid="gates">
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
        reserve={[16, 30]}
      >
        {log.length === 0 ? (
          <p className="empty-note">No authorised action has been recorded yet.</p>
        ) : (
          <ul className="blist" data-testid="autonomy-log">
            {log.map((e) => {
              const a = e.authz;
              const by = authorisation(events, e);
              return (
                <Row
                  key={e.seq}
                  name={e.summary}
                  sub={
                    a ? `Authorised by ${authzText(a).toLowerCase()} · ${stamp(a.at)}` : undefined
                  }
                  state={
                    <Chip tone={a?.by === "policy" ? "policy" : "done"}>
                      {a?.by === "policy" ? "Policy stamp" : "Approved"}
                    </Chip>
                  }
                >
                  <span className="soon-row">
                    <AppLink
                      to={trace}
                      className="pill"
                      aria-label={`Authorisation for: ${e.summary} (${by.summary})`}
                    >
                      See authorisation
                    </AppLink>
                    {e.type === "data.transfer" && field(e, "direction") === "out" && (
                      <>
                        <Placeholder label="Undo" compact />
                        <Placeholder label="Report" compact />
                      </>
                    )}
                  </span>
                </Row>
              );
            })}
          </ul>
        )}
      </Section>
    </Page>
  );
}
