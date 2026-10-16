// TILO-T-WORLD: everything laid over the live stage that is about the agents: the hover stats card now, the agent
// panel ("Talk to") and the team meeting next. It reads the same replayed events as the Story (useWorldFacts), and the
// stage's spotlight (display state), and writes nothing of its own.
import type { RoomClient } from "../../park/api/live/meetingHall";
import { openAgent, useSpotlight } from "../../world/spotlight";
import { useWorldFacts } from "../../world/useWorldFacts";
import { AgentCard } from "./AgentCard";
import { AgentPanel } from "./AgentPanel";

export function AgentLayer({ worldId, rooms }: { worldId: string; rooms: RoomClient | null }) {
  const facts = useWorldFacts(worldId, rooms);
  const spot = useSpotlight(worldId);
  const hovered = spot.hover && spot.opened !== spot.hover ? facts.stats.get(spot.hover) : null;
  const opened = spot.opened ? facts.stats.get(spot.opened) : null;
  return (
    <>
      {hovered && spot.point ? <AgentCard stats={hovered} at={spot.point} /> : null}
      {opened ? (
        <AgentPanel
          key={opened.id}
          worldId={worldId}
          stats={opened}
          facts={facts}
          events={facts.events}
          rooms={rooms}
          onClose={() => openAgent(worldId, null)}
        />
      ) : null}
    </>
  );
}
