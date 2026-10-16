// TILO-T-WORLD: one conversation through the existing meeting-room routes, for the agent panel and the team meeting.
// It convenes the room on the first question (not before: an open room holds the world's one room slot), asks, reads
// the room back, adjourns, and confirms a change the agent proposed (MR-07). It never decides anything: the room's
// words and outcomes are the API's, and a refusal is shown as the API answered it (roomFault).
import type { Event } from "@tilo/contracts";
import { useCallback, useEffect, useRef, useState } from "react";
import { TiloApiError } from "../../api/http";
import {
  type Room,
  type RoomClient,
  confirmChange,
  roomPath,
} from "../../park/api/live/meetingHall";
import {
  type Seat,
  adjournRoom,
  askTurn,
  conveneRoom,
  roomFault,
} from "../../park/api/live/roomTalk";

/** Rooms the events show as open: convened and not yet adjourned (MR-05). */
export function openRoomsOf(events: readonly Event[]): string[] {
  const open = new Set<string>();
  for (const e of events) {
    const id = (e.data as { room_id?: unknown } | null)?.room_id;
    if (typeof id !== "string") continue;
    if (e.type === "meeting.convened") open.add(id);
    if (e.type === "meeting.adjourned") open.delete(id);
  }
  return [...open];
}

export interface RoomTalk {
  readonly room: Room | null;
  readonly busy: boolean;
  readonly error: string;
  /** proposal id -> what the API said when the change was confirmed ("planning started" and so on). */
  readonly confirmed: Readonly<Record<string, string>>;
  send(to: string, mode: "quick" | "thinking", text: string): Promise<boolean>;
  adjourn(): Promise<void>;
  confirm(proposalId: string, text: string): Promise<void>;
}

const PLANNING: Readonly<Record<string, string>> = {
  pending: "queued: the planner has not started on it yet",
  started: "accepted: the planner has started on it",
  failed: "accepted, but planning failed to start",
};

export function useRoomTalk(
  client: RoomClient | null,
  worldId: string,
  seat: Seat | null,
  events: readonly Event[],
): RoomTalk {
  const [room, setRoom] = useState<Room | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmed, setConfirmed] = useState<Record<string, string>>({});
  const live = useRef(true);
  const held = useRef(false);
  const eventsRef = useRef(events);
  eventsRef.current = events;
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  const run = useCallback(async (job: () => Promise<void>): Promise<boolean> => {
    if (held.current) return false;
    held.current = true;
    setBusy(true);
    setError("");
    try {
      await job();
      return true;
    } catch (e) {
      if (live.current) setError(roomFault(e));
      return false;
    } finally {
      held.current = false;
      if (live.current) setBusy(false);
    }
  }, []);

  const send = useCallback(
    (to: string, mode: "quick" | "thinking", text: string) =>
      run(async () => {
        if (!client || !seat) throw new Error("no room");
        let current = room;
        if (!current || current.state !== "open") {
          try {
            current = await conveneRoom(client, worldId, seat);
          } catch (e) {
            if (!(e instanceof TiloApiError) || e.code !== "room_open") throw e;
            // A room of this person's is still open on the world (one at a time): close it, then convene once more.
            for (const id of openRoomsOf(eventsRef.current)) {
              await adjournRoom(client, worldId, id).catch(() => undefined);
            }
            current = await conveneRoom(client, worldId, seat);
          }
          if (live.current) setRoom(current);
        }
        const next = await askTurn(client, worldId, current.room_id, to, mode, text);
        if (live.current) setRoom(next);
      }),
    [client, room, run, seat, worldId],
  );

  const adjourn = useCallback(async () => {
    if (!client || !room) return;
    await run(async () => {
      const closed = await adjournRoom(client, worldId, room.room_id);
      if (live.current) setRoom(closed);
    });
  }, [client, room, run, worldId]);

  const confirm = useCallback(
    async (proposalId: string, text: string) => {
      if (!client || !room) return;
      await run(async () => {
        const said = await confirmChange(client, roomPath(worldId, room.room_id), proposalId, text);
        const planning = /planning (\w+)/.exec(said)?.[1] ?? "";
        if (live.current) setConfirmed((c) => ({ ...c, [proposalId]: PLANNING[planning] ?? said }));
      });
    },
    [client, room, run, worldId],
  );

  return { room, busy, error, confirmed, send, adjourn, confirm };
}
