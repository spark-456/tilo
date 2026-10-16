// TILO-T-WORLD: the one hook the hover card, the agent panel and the Conversations chat read. It takes the same
// replayed event slice the Story reads (HR-1: Story, Trace, chat and the stage share one source), the world's layout,
// and (when a room client exists) the archive's words for the room turns; and derives the conversations and every
// agent's stats from them. Nothing here is fetched except the layout and the rooms the events name.
import type { Event, Layout } from "@tilo/contracts";
import { useEffect, useMemo, useRef, useState } from "react";
import { useClient } from "../api/ClientProvider";
import { type RoomClient, readRoom } from "../park/api/live/meetingHall";
import { useRemote } from "../park/shared/remote";
import { type AgentStats, agentStatsOf } from "./agentStats";
import { type Message, conversationsOf, withWords } from "./conversations";
import { useReplayedLog } from "./replay";
import { agentNames } from "./runSummary";

export interface WorldFacts {
  readonly layout: Layout | null;
  readonly events: readonly Event[];
  readonly names: ReadonlyMap<string, string>;
  readonly messages: readonly Message[];
  readonly stats: ReadonlyMap<string, AgentStats>;
  /** The Meeting Hall's room ids named by the events, in the order they were convened. */
  readonly rooms: readonly string[];
}

/** The words of a room turn, once the archive gave them (`${room}:${turn}:${side}`). */
export type RoomTexts = ReadonlyMap<string, string>;

const key = (room: string, turn: number, side: string) => `${room}:${turn}:${side}`;

/** Reads each room the events name, again whenever it gains a turn or a reply, and keeps what it said.
 * A room that cannot be read (no client, no access, a 503) leaves its turns unworded: nothing is invented. */
export function useRoomTexts(rooms: RoomClient | null, worldId: string, events: readonly Event[]) {
  const [texts, setTexts] = useState<RoomTexts>(new Map());
  const seen = useRef("");
  const signature = useMemo(() => {
    const counts = new Map<string, number>();
    for (const e of events) {
      if (e.type !== "meeting.asked" && e.type !== "meeting.replied") continue;
      const room = (e.data as { room_id?: unknown } | null)?.room_id;
      if (typeof room === "string") counts.set(room, (counts.get(room) ?? 0) + 1);
    }
    return [...counts].map(([room, n]) => `${room}=${n}`).join(",");
  }, [events]);
  useEffect(() => {
    if (!rooms || !signature || seen.current === signature) return;
    seen.current = signature;
    let live = true;
    const ids = signature.split(",").map((p) => p.split("=")[0] as string);
    for (const id of ids) {
      readRoom(rooms, worldId, id).then(
        (room) => {
          if (!live) return;
          setTexts((prev) => {
            const next = new Map(prev);
            for (const t of room.turns) {
              if (t.text) next.set(key(id, t.turn, "asked"), t.text);
              if (t.reply?.text) next.set(key(id, t.turn, "replied"), t.reply.text);
            }
            return next;
          });
        },
        () => undefined, // unreadable: the turn stays unworded
      );
    }
    return () => {
      live = false;
    };
  }, [rooms, worldId, signature]);
  return texts;
}

export function useWorldFacts(worldId: string, rooms: RoomClient | null = null): WorldFacts {
  const client = useClient();
  const { events } = useReplayedLog(client, worldId);
  const [layoutState] = useRemote("load the world", (signal) => client.getLayout(worldId, signal));
  const layout = layoutState.status === "ready" ? layoutState.value : null;
  const texts = useRoomTexts(rooms, worldId, events);
  return useMemo<WorldFacts>(() => {
    if (!layout)
      return {
        layout: null,
        events,
        names: new Map(),
        messages: [],
        stats: new Map(),
        rooms: [],
      };
    const base = conversationsOf(layout, events);
    const messages = withWords(base, (room, turn, side) => texts.get(key(room, turn, side)));
    const roomIds = [
      ...new Set(base.filter((m) => m.kind === "convened").map((m) => m.room ?? "")),
    ];
    return {
      layout,
      events,
      names: agentNames(layout),
      messages,
      stats: agentStatsOf(layout, events),
      rooms: roomIds.filter(Boolean),
    };
  }, [layout, events, texts]);
}
