// S-21 Artifact history, restore and "Why is this here?" (PRD 18.3, 13.3, 13.4). Every artifact
// event of the run is a row: which artifact and version, what happened and, from the event's own
// `cause`, why it exists. Titles come from the artifact's label, else from client.getDelivery.
// Restore (always a new version, never a deletion) is not built, so its control is a placeholder
// on every version; "Why is this here?" opens the Trace. No design export covers this screen:
// cards and rows after "Tilo Worlds.dc.html", neutral role tokens (design/source/INDEX.md, S-21).
import type { Event } from "@tilo/contracts";
import { useClient } from "../api/ClientProvider";
import { AppLink } from "./AppLink";
import { Placeholder } from "./Placeholder";
import { Chip, Page, Row, Section, Stats, field, useFixtureRun, words } from "./kit";
import { useRemote } from "./remote";

interface Ref {
  readonly artifact_id: string;
  readonly version: number;
  readonly label?: string;
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
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [delivery] = useRemote("load the artifact titles", () => client.getDelivery(worldId));
  const titles = new Map(
    delivery.status === "ready" ? delivery.value.artifacts.map((a) => [a.id, a.title]) : [],
  );
  const mine = events.filter((e) => e.type.startsWith("artifact.") && ref(e));
  const ids = new Set(mine.map((e) => ref(e)?.artifact_id));
  const trace = `/world/${encodeURIComponent(worldId)}/trace`;
  return (
    <Page
      testid="artifact-history"
      title="Artifact history"
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
          <ul className="blist" data-testid="artifact-rows">
            {mine.map((e) => {
              const r = ref(e);
              const why = events.find((x) => x.id === e.cause);
              const [label, tone] = LABEL[e.type as keyof typeof LABEL] ?? [words(e.type), "fyi"];
              const title =
                r?.label ??
                titles.get(r?.artifact_id ?? "") ??
                words((r?.artifact_id ?? "").replace(/^art_/, ""));
              return (
                <Row
                  key={e.seq}
                  name={`${title}, version ${r?.version}`}
                  sub={
                    <>
                      {e.summary}
                      {why && <> Because: {why.summary}</>}
                    </>
                  }
                  state={<Chip tone={tone}>{label}</Chip>}
                >
                  <span className="soon-row">
                    <AppLink
                      to={trace}
                      className="pill"
                      aria-label={`Why is this here? ${title}, version ${r?.version}, ${label.toLowerCase()}`}
                    >
                      Why is this here?
                    </AppLink>
                    <Placeholder label="Restore" compact />
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
