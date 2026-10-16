// WORLD-LIVE: the live isometric stage inside the Park World page, so a run's buildings rise and its agents walk and
// talk on the page the person is already reading (before this the page drew a static text diagram and the stage sat
// behind an "Open live view" link). It is the same stage as /world/:id/stage: the client's own layout and events, drawn
// by `useClientWorld`; nothing is drawn or moved except by a recorded event (HR-1). Loaded as a chunk of its own.
import { useMemo } from "react";
import { useClient } from "../api/ClientProvider";
import { createRoomClient, readRoom } from "../park/api/live/meetingHall";
import { Stage } from "../stage/Stage";
import { useRunStatus } from "../world/runLog";
import { type RoomWords, useClientWorld } from "../world/useClientWorld";
import { AgentLayer } from "./live/AgentLayer";
import { Conversations } from "./live/Conversations";

export default function LiveStageEmbed({ worldId }: { worldId: string }) {
  const client = useClient();
  // The words of a Meeting Hall turn live only in the archive (MR-12); the stage reads them from the room, as the
  // Meeting Hall panel does, when the turn is recorded. No room client (a demo, no API) means no bubble text.
  const rooms = useMemo(createRoomClient, []);
  const words = useMemo<RoomWords>(
    () => async (roomId, turn, kind) => {
      if (!rooms) return null;
      const t = (await readRoom(rooms, worldId, roomId)).turns.find((x) => x.turn === turn);
      return (kind === "asked" ? t?.text : t?.reply?.text) ?? null;
    },
    [rooms, worldId],
  );
  const world = useClientWorld(client, worldId, words);
  const status = useRunStatus(client, worldId);
  return (
    <div
      className={`park-world-livestage${status === "completed" ? " tw-light" : ""}`}
      data-testid="live-stage"
      data-run-status={status}
    >
      <Stage
        key={worldId}
        landmark={false}
        onWorld={world.onWorld}
        seq={world.seq}
        selected={world.selected}
        layout={world.layout}
        worldId={world.worldId}
        paused={status === "paused"}
      />
      <AgentLayer worldId={worldId} rooms={rooms} />
      {world.note ? (
        <div
          className="park-world-livenote"
          data-testid="live-world-note"
          role={world.retry ? "alert" : "status"}
        >
          <p>{world.note}</p>
          {world.retry ? (
            <button type="button" className="secondary" onClick={world.retry}>
              Try again
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** TILO-T-WORLD: the agents' chat for the World page's Chat tab; it lives in this chunk so the page imports one module. */
export function LiveChat({ worldId }: { worldId: string }) {
  const rooms = useMemo(createRoomClient, []);
  return <Conversations worldId={worldId} rooms={rooms} />;
}
