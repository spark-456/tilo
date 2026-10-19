// TILO-T-WORLD: "Talk to an agent" and "Convene team" over the existing meeting-room routes (ADR-0028,
// services/api meeting_room.py). Nothing is added to the API: a 1:1 is a room with the agent's seat as the API checks
// it (MR-02), a team is a Lead plus at most ROOM_MAX_AGENTS of its own district. A room turn is T0/T1 (a read and a
// recorded note): it authorises nothing (MR-11), and a refusal is worded as the API answered it.
import type { Event, Layout } from "@tilo/contracts";
import { TiloApiError } from "../../../api/http";
import { type Room, type RoomClient, readRoom, roomOf, roomPath } from "./meetingHall";

/** config/meeting_room.yaml `max_agents` (6) counts the lead; the API answers `bad_attendees` past it. */
export const ROOM_MAX_AGENTS = 5;

export interface Seat {
  readonly lead: string;
  readonly agents: string[];
}

const WORKERS = new Set(["specialist", "writer", "verifier"]);

/** The district an agent was recorded in: a Lead's own, else the first event naming it (the API's own `locate`). */
function districtOf(layout: Layout, events: readonly Event[], id: string): string | null {
  for (const level of layout.semantic.levels)
    for (const district of level.districts) if (district.lead === id) return district.id;
  const e = events.find((x) => (x.actor === id || x.target === id) && x.district);
  return e?.district ?? null;
}

/** Where one agent sits to be talked to: a worker beside its district's Lead, a Lead or the Director alone. */
export function seatFor(layout: Layout, events: readonly Event[], id: string): Seat | null {
  const agent = layout.semantic.agents.find((a) => a.id === id);
  if (!agent) return null;
  if (agent.rank === "director" || agent.rank === "lead") return { lead: id, agents: [] };
  if (!WORKERS.has(agent.rank)) return null;
  const district = districtOf(layout, events, id);
  const lead = layout.semantic.levels
    .flatMap((l) => l.districts)
    .find((d) => d.id === district)?.lead;
  return lead ? { lead, agents: [id] } : null;
}

/** A team room: `lead` with those of `wanted` the API would accept (its district's workers, or the Director's
 * Leads), in the order given, at most ROOM_MAX_AGENTS. */
export function teamSeat(
  layout: Layout,
  events: readonly Event[],
  lead: string,
  wanted: readonly string[],
): Seat | null {
  const head = layout.semantic.agents.find((a) => a.id === lead);
  if (!head || (head.rank !== "director" && head.rank !== "lead")) return null;
  const district = districtOf(layout, events, lead);
  const ranks = new Map(layout.semantic.agents.map((a) => [a.id, a.rank]));
  const ok = (id: string) => {
    if (id === lead) return false;
    const rank = ranks.get(id);
    if (head.rank === "director") return rank === "lead";
    return rank !== undefined && WORKERS.has(rank) && districtOf(layout, events, id) === district;
  };
  return { lead, agents: wanted.filter(ok).slice(0, ROOM_MAX_AGENTS) };
}

export async function conveneRoom(client: RoomClient, worldId: string, seat: Seat): Promise<Room> {
  return roomOf(await client.postJson(roomPath(worldId), seat), worldId);
}

/** One question to one agent in an open room; resolves with the room read back (the reply is in the turn). */
export async function askTurn(
  client: RoomClient,
  worldId: string,
  roomId: string,
  to: string,
  mode: "quick" | "thinking",
  text: string,
): Promise<Room> {
  await client.postJson(`${roomPath(worldId, roomId)}/turns`, { to, mode, text });
  return readRoom(client, worldId, roomId);
}

export async function adjournRoom(
  client: RoomClient,
  worldId: string,
  roomId: string,
): Promise<Room> {
  return roomOf(await client.postJson(`${roomPath(worldId, roomId)}/adjourn`, {}), worldId);
}

const BY_CODE: Readonly<Record<string, string>> = {
  room_open: "A meeting room is already open on this world. Close it first.",
  world_paused: "This world is paused, so no room can open or answer.",
  turn_in_flight: "The agent is still answering. Wait for the reply, then ask again.",
  room_closed: "That room has closed, so nothing more can be asked in it.",
  room_limit: "This room has used up its credits, so it can take no more questions.",
  bad_attendees: "The room does not allow that group. Pick fewer agents, from one district.",
  not_allowed: "Your role on this world does not allow calling the team.",
  demo_session: "The sample company has no real team to talk to.",
  access_lost: "Your access to these agents changed, so the room was closed.",
  no_layout: "This world has no map yet, so there is nobody to call.",
  write_failed: "The room could not record that. Nothing was asked. Try again.",
  store_unavailable: "The room's record is unavailable right now. Try again shortly.",
};

/** What a person reads when a room call fails: the API's own refusal, in words; never a guessed outcome. */
export function roomFault(error: unknown): string {
  if (error instanceof TiloApiError) {
    const word = error.code ?? error.refusal;
    const known = word ? BY_CODE[word] : undefined;
    if (known) return known;
    if (error.status === 503)
      return "Meeting rooms are not switched on in this build yet, so nothing was asked.";
    if (error.status === 404)
      return "That room or world was not found for your sign-in, or you no longer have access.";
    if (error.status === 429) return "Too many questions at once. Wait a moment and try again.";
  }
  return "Could not reach the room. Nothing was asked.";
}
