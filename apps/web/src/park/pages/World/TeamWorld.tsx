// BQ-CTX-TEAMWORLD (ADR-0040 decisions 4, 6 and 8; FR-TEAM-03/05): what a teammate sees of a world that is not theirs.
// `TeamWorld` is a read-only page: the world's districts as the Viewer sees them, links to the read lenses (Story,
// Trace, Delivery) and the team's work items. It has no pause, answer, approve or share control and nothing on it
// moves (HR-1: nothing is recorded in this world for a teammate's item). A world this person may not read, and one
// that does not exist, are the same ordinary missing world. `TeamItems` is a read model: list rows, never a link.
import { useState } from "react";
import { type ShareClient, readSharedWorld, readTeamItems } from "../../api/live/teamShares";
import type { WorkItemClient } from "../../api/live/workItems";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi } from "../../app/context";
import { Button, PageSheet } from "../../components";
import { AddWorkItem } from "./AddWorkItem";
import { GoLink } from "./Side";
import { useRead } from "./TeamShare";

const STATUS = { open: "Open", done: "Done" } as const;

function TeamItemsList({
  client,
  worldId,
  version,
}: { client: ShareClient; worldId: string; version: number }) {
  const api = useParkApi();
  const [view, reload] = useRead(async () => {
    const [got, team] = await Promise.all([
      readTeamItems(client, worldId),
      api.getTeam().then(
        (r) => r.data,
        () => null, // a name is a nicety: without the directory the row says "A teammate"
      ),
    ]);
    const names = new Map((team?.people ?? []).map((p) => [p.id, p.name]));
    return {
      ...got,
      items: got.items.map((i) => ({ ...i, who: names.get(i.owner) ?? "A teammate" })),
    };
  }, [client, worldId, api, version]);
  if (view.status === "loading") return <output>Loading the team’s work items…</output>;
  if (view.status === "failed")
    return (
      <>
        <p role="alert">{view.message}</p>
        <Button variant="secondary" size="sm" onClick={reload}>
          Try again
        </Button>
      </>
    );
  const { items, truncated } = view.value;
  if (items.length === 0)
    return (
      <p className="park-world-teamnote">
        No work items have been added in this world yet. Items added before it was shared stay
        personal.
      </p>
    );
  return (
    <>
      <ul className="park-world-teamlist" aria-label="Team work items">
        {items.map((i) => (
          <li key={i.id} className="park-world-teamrow">
            <span className="park-world-teamname">{i.title}</span>
            <span className="park-world-teamnote">
              {`${i.who} · ${STATUS[i.status]}${i.due ? ` · due ${i.due}` : ""}`}
            </span>
          </li>
        ))}
      </ul>
      {truncated ? <p className="park-world-teamnote">Only the first items are shown.</p> : null}
    </>
  );
}

/**
 * The team's items made in this world, and the form that adds one (BQ-CTX-TEAMWORLD, TSW-5). `auto` reads at once
 * (a teammate's page); otherwise on a click. An item added here makes the list read again, so the row shown is
 * the server's.
 */
export function TeamItems({
  client,
  worldId,
  auto,
}: { client: ShareClient & WorkItemClient; worldId: string; auto: boolean }) {
  const [asked, setAsked] = useState(auto);
  const [version, setVersion] = useState(0);
  return (
    <>
      <section className="park-world-proposals" aria-label="Team work items">
        <h2>Team work items</h2>
        {asked ? (
          <TeamItemsList client={client} worldId={worldId} version={version} />
        ) : (
          <Button variant="secondary" size="sm" onClick={() => setAsked(true)}>
            Show team work items
          </Button>
        )}
      </section>
      <AddWorkItem client={client} worldId={worldId} onAdded={() => setVersion((n) => n + 1)} />
    </>
  );
}

export function TeamWorld({
  client,
  worldId,
  app,
}: { client: ShareClient & WorkItemClient; worldId: string; app: AppCtx }) {
  const [view, reload] = useRead(() => readSharedWorld(client, worldId), [client, worldId]);
  const id = encodeURIComponent(worldId);
  const crumb = (
    <GoLink className="park-world-back" href="#worlds" onGo={() => app.go("worlds")}>
      Worlds
    </GoLink>
  );
  let body = <output>Loading this world…</output>;
  let title = "World";
  if (view.status === "failed" && view.missing) {
    title = "World not found";
    body = <p className="park-world-meta">Tilo could not find that world.</p>;
  } else if (view.status === "failed") {
    body = (
      <>
        <p role="alert">{view.message}</p>
        <Button variant="secondary" size="sm" onClick={reload}>
          Try again
        </Button>
      </>
    );
  } else if (view.status === "ready") {
    title = "Shared world";
    body = (
      <>
        <p className="park-world-meta">You can read this world. Only its owner can change it.</p>
        <nav aria-label="Run views" className="park-world-lenses">
          <a href={`/world/${id}/story`}>Story</a>
          <a href={`/world/${id}/trace`}>Trace</a>
          <a href={`/world/${id}/delivery`}>Delivery</a>
        </nav>
        <ul className="park-world-teamlist" aria-label="Districts">
          {view.value.districts.map((d) => (
            <li key={d.id} className="park-world-teamrow">
              <span className="park-world-teamname">{d.name}</span>
              <span className="park-world-teamnote">{d.summary}</span>
            </li>
          ))}
        </ul>
        {view.value.hasHiddenDistricts ? (
          <p className="park-world-teamnote">Some districts are not shown to you.</p>
        ) : null}
        <TeamItems client={client} worldId={worldId} auto />
      </>
    );
  }
  return (
    <div className="park-world-root" data-testid="park-page-world" data-world-id={worldId}>
      <PageSheet>
        <nav aria-label="Breadcrumb" className="park-world-crumb">
          {crumb}
        </nav>
        <h1 className="park-world-h1" tabIndex={-1}>
          {title}
        </h1>
        {body}
      </PageSheet>
    </div>
  );
}
