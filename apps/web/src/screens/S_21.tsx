// S-21 Artifact history, restore and "Why is this here?" (PRD 18.3, 13.3, 13.4). Every artifact
// event of the run is a row: which version, what happened and, from the event's own `cause`, why it
// exists. Restore (always a new version, never a deletion) is not built, so its control is a
// placeholder; "Why is this here?" opens the Trace. No design export covers this screen: cards and
// rows after "Tilo Worlds.dc.html", neutral role tokens (design/source/INDEX.md, S-21).
import type { Event } from "@tilo/contracts";
import { AppLink } from "./AppLink";
import { Placeholder } from "./Placeholder";
import { Chip, Page, Row, Section, Stats, field, useFixtureRun, words } from "./kit";

interface Ref {
  readonly artifact_id: string;
  readonly version: number;
}
const ref = (e: Event): Ref | null => {
  const r = field(e, "artifact") as Ref | undefined;
  return r?.artifact_id ? r : null;
};
const LABEL = {
  "artifact.created": ["Created", "fyi"],
  "artifact.reviewed": ["Checked", "done"],
  "artifact.delivered": ["Delivered", "done"],
} as const;

export function S_21() {
  const { events, worldId } = useFixtureRun();
  const mine = events.filter((e) => e.type.startsWith("artifact.") && ref(e));
  const ids = new Set(mine.map((e) => ref(e)?.artifact_id));
  const trace = `/world/${encodeURIComponent(worldId)}/trace`;
  return (
    <Page
      testid="artifact-history"
      title="Artifact history and restore"
      sub="Every version of everything Tilo made, and the reason each one exists."
    >
      <Stats
        items={[
          ["Artifacts", ids.size],
          ["Events", mine.length],
          ["Delivered", mine.filter((e) => e.type === "artifact.delivered").length],
        ]}
      />
      <Section
        title="History"
        note="Restoring a version makes a new version. Nothing is ever deleted."
        reserve={[12, 27]}
      >
        {mine.length === 0 ? (
          <p className="empty-note">No artifact has been recorded yet.</p>
        ) : (
          <ul className="rows" data-testid="artifact-rows">
            {mine.map((e) => {
              const r = ref(e);
              const why = events.find((x) => x.id === e.cause);
              const [label, tone] = LABEL[e.type as keyof typeof LABEL] ?? [words(e.type), "fyi"];
              return (
                <Row
                  key={e.seq}
                  name={`${words((r?.artifact_id ?? "").replace(/^art_/, ""))}, version ${r?.version}`}
                  sub={
                    <>
                      {e.summary}
                      {why && <> Because: {why.summary}</>}
                    </>
                  }
                  state={<Chip tone={tone}>{label}</Chip>}
                >
                  <span className="soon-row">
                    <AppLink to={trace} className="pill">
                      Why is this here?
                    </AppLink>
                    {e.type === "artifact.created" && <Placeholder label="Restore" compact />}
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
