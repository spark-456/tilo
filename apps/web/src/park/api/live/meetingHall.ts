import type { MeetingRoom as Room } from "@tilo/contracts";
export type { MeetingRoom as Room } from "@tilo/contracts";
import { API_URL, appCheckToken, authToken, sessionView } from "../../../api/ClientProvider";
import { HttpClient, TiloApiError } from "../../../api/http";
import roomGuard from "./meetingRoom.guard.js";

export type RoomClient = Pick<HttpClient, "getJson" | "postJson">;
export function createRoomClient(): RoomClient | null {
  return API_URL?.trim() && !sessionView.demo()
    ? new HttpClient({ baseUrl: API_URL, appCheckToken, authToken })
    : null;
}
export interface Attendee {
  id: string;
  rank: string;
  district: string | null;
}
const record = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v);
const bad = () => new TiloApiError("Could not read the Meeting Hall reply.", 200, true);
export function roomOf(v: unknown, worldId: string): Room {
  if (!roomGuard(v) || !record(v) || v.world_id !== worldId) throw bad();
  return v as unknown as Room;
}
/** MR-02: the same layout + recorded district association the server uses; nothing inferred from names. */
export async function attendees(client: RoomClient, worldId: string): Promise<Attendee[]> {
  const path = `/worlds/${encodeURIComponent(worldId)}`;
  const missing = Symbol("layout not yet available");
  const [layout, feed] = await Promise.all([
    client.getJson(`${path}/layout`).catch((error: unknown) => {
      if (error instanceof TiloApiError && error.status === 404) return missing;
      throw error;
    }),
    client.getJson(`${path}/events`),
  ]);
  // LIVE-LAYOUT / FR-WLD-05: only a successful events read establishes a readable world.
  // Missing layout cannot supply attendees; never invent agents or suppress an access error.
  if (layout === missing && record(feed) && Array.isArray(feed.events)) return [];
  if (
    !record(layout) ||
    !record(layout.semantic) ||
    !Array.isArray(layout.semantic.agents) ||
    !Array.isArray(layout.semantic.levels) ||
    !record(feed) ||
    !Array.isArray(feed.events)
  )
    throw bad();
  const events = feed.events;
  const districts = new Map<string, string>();
  for (const level of layout.semantic.levels) {
    if (!record(level) || !Array.isArray(level.districts)) throw bad();
    for (const d of level.districts) {
      if (!record(d) || typeof d.lead !== "string" || typeof d.id !== "string") throw bad();
      districts.set(d.lead, d.id);
    }
  }
  return layout.semantic.agents.map((a) => {
    if (!record(a) || typeof a.id !== "string" || typeof a.rank !== "string") throw bad();
    const event = events.find(
      (e) => record(e) && (e.actor === a.id || e.target === a.id) && typeof e.district === "string",
    );
    return {
      id: a.id,
      rank: a.rank,
      district:
        districts.get(a.id) ??
        (record(event) && typeof event.district === "string" ? event.district : null),
    };
  });
}
export function roomPath(worldId: string, roomId?: string): string {
  return `/v1/worlds/${encodeURIComponent(worldId)}/rooms${roomId ? `/${encodeURIComponent(roomId)}` : ""}`;
}
export async function readRoom(client: RoomClient, worldId: string, roomId: string): Promise<Room> {
  const r = roomOf(await client.getJson(roomPath(worldId, roomId)), worldId);
  if (r.room_id !== roomId) throw bad();
  return r;
}
export async function confirmChange(
  client: RoomClient,
  path: string,
  proposal_id: string,
  text: string,
): Promise<string> {
  const r = await client.postJson(`${path}/changes`, { proposal_id, text });
  if (
    !record(r) ||
    r.proposal_id !== proposal_id ||
    !["pending", "started", "failed"].includes(String(r.planning))
  )
    throw bad();
  return `Change recorded; planning ${r.planning}.`;
}
