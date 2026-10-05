// S-04 levels panel (PRD 18.3), after the "Levels · top to bottom" column of design/source "Tilo
// World Player.dc.html": the world's size, its counts, and one card per level with how many of its
// buildings are finished and the latest thing that happened there. Every figure comes from the
// layout and the recorded events up to the replay point (HR-1); before a layout there is no panel.
import type { Event } from "@tilo/contracts";
import { useClient } from "../api/ClientProvider";
import { levelRows } from "../world/levels";
import { reduce } from "../world/reducer";
import { useReplayedLog } from "../world/replay";
import { AppLink } from "./AppLink";
import { Chip, plural, words } from "./kit";
import { useRemote } from "./remote";

export function LevelsPanel({
  worldId,
  replayed = null,
}: { worldId: string; replayed?: readonly Event[] | null }) {
  const client = useClient();
  const log = useReplayedLog(client, worldId);
  const events = replayed ?? log.events;
  const [layoutRemote] = useRemote("load the world", (signal) => client.getLayout(worldId, signal));
  if (layoutRemote.status !== "ready") return <aside className="levels-panel" aria-hidden="true" />;
  const layout = layoutRemote.value;
  const rows = levelRows(layout, reduce(layout, events), events);
  const buildings = layout.semantic.levels.reduce(
    (n, level) => n + level.districts.reduce((m, d) => m + d.buildings.length, 0),
    0,
  );
  const gates = layout.semantic.gates.length;
  return (
    <aside className="levels-panel" aria-label="Levels" data-testid="levels-panel">
      <Chip tone="fyi">{words(layout.tier)}</Chip>
      <p className="levels-counts">
        {plural(layout.semantic.agents.length, "agent")} · {plural(buildings, "building")} ·{" "}
        {plural(gates, "gate")}
      </p>
      <h2>Levels · top to bottom</h2>
      <ul>
        {rows.map((row) => (
          <li key={row.id}>
            <AppLink
              to={`/world/${encodeURIComponent(worldId)}/inspect/${encodeURIComponent(row.id)}`}
              className="level-card"
              data-active={row.active || undefined}
            >
              <span className="level-badge" aria-hidden="true">
                L{row.number}
              </span>
              <span className="level-name">{row.name}</span>
              <span className="level-pct">{`${row.percent}%`}</span>
              <progress
                max={100}
                value={row.percent}
                aria-label={`${row.name}: buildings finished`}
              />
              <span className="level-line">{row.line ?? "Nothing recorded here yet"}</span>
            </AppLink>
          </li>
        ))}
      </ul>
    </aside>
  );
}
