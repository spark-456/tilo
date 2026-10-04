// S-13 Library and Memory Vault (PRD 18.3, 13.1): what Tilo has made and what it remembers.
// The library lists the artifact.delivered events of the run (nothing is "finished" before its
// event, HR-1); client.getDelivery only supplies titles and kinds for those artifacts. Memory comes
// from the recorded memory.hit and memory.saved events (none in the fixture run, so the vault says
// so). No design export covers this screen: cards and rows after "Tilo Worlds.dc.html", neutral
// role tokens (design/source/INDEX.md, S-13).
import type { Event } from "@tilo/contracts";
import { useState } from "react";
import { useClient } from "../api/ClientProvider";
import type { DeliveredArtifact } from "../api/client";
import { AppLink } from "./AppLink";
import {
  EmptyState,
  Page,
  Row,
  Section,
  Stats,
  doneState,
  field,
  useFixtureRun,
  words,
} from "./kit";
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

const ref = (e: Event) =>
  field(e, "artifact") as { artifact_id: string; version: number; label?: string };

export function S_13() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [delivery] = useRemote("load the library", () => client.getDelivery(worldId));
  const known = new Map<string, DeliveredArtifact>(
    delivery.status === "ready" ? delivery.value.artifacts.map((a) => [a.id, a]) : [],
  );
  const [query, setQuery] = useState("");
  const delivered = events.filter((e) => e.type === "artifact.delivered");
  const rows = delivered.map((e) => {
    const a = ref(e);
    const meta = known.get(a.artifact_id);
    return {
      seq: e.seq,
      name: a.label ?? meta?.title ?? words(a.artifact_id.replace(/^art_/, "")),
      sub: `${words(meta?.kind ?? "artifact")} · version ${a.version}`,
    };
  });
  const q = query.trim().toLowerCase();
  const shown = rows.filter((r) => q === "" || r.name.toLowerCase().includes(q));
  const count = (type: string) => events.filter((e) => e.type === type).length;
  return (
    <Page
      testid="library"
      title="Library"
      sub="What Tilo has made for you, and what it remembers for next time."
    >
      <Stats
        items={[
          ["Deliverables", delivered.length, doneState(delivered.length, "Delivered")],
          ["Memory reuses", count("memory.hit"), doneState(count("memory.hit"), "Reused")],
          ["Items remembered", count("memory.saved"), doneState(count("memory.saved"), "Kept")],
        ]}
      />
      <Section
        title="Deliverables"
        note="Finished work, listed as each one is delivered."
        reserve={[9, 11]}
        action={
          <label className="search-field">
            <span className="visually-hidden">Search the library</span>
            <input
              type="search"
              value={query}
              placeholder="Search the library"
              autoComplete="off"
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
        }
      >
        {delivered.length === 0 ? (
          <EmptyState
            testid="library-empty"
            title="Nothing delivered yet"
            line="Finished work is listed here as each one is delivered."
            action={{ label: "Start a task", to: "/" }}
          />
        ) : (
          <ul className="blist" data-testid="library-rows">
            {shown.length === 0 && (
              <li className="empty-note" data-testid="library-nomatch">
                No deliverable matches that search.
              </li>
            )}
            {shown.map((r) => (
              <Row key={r.seq} name={r.name} sub={r.sub}>
                <AppLink to="/library/artifacts" className="pill">
                  Version history
                </AppLink>
              </Row>
            ))}
          </ul>
        )}
      </Section>
      <Section
        title="Memory Vault"
        note="Tilo reuses a result only after a check accepts it. Forgetting an item is not available yet."
      >
        {count("memory.hit") + count("memory.saved") === 0 && (
          <EmptyState
            compact
            testid="memory-empty"
            title="Nothing remembered yet"
            line="No memory event has been recorded for this run."
          />
        )}
        <ul className="blist">
          {LAYERS.map(([layer, what]) => (
            <Row key={layer} name={layer} sub={what} />
          ))}
        </ul>
      </Section>
    </Page>
  );
}
