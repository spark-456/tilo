/**
 * TILO-T-WORLD steps 3 and 4 (MR-02, MR-03, MR-07): "Talk to an agent" and "Convene team" use the existing room
 * routes exactly as the API checks them: a worker sits with its district's Lead, a Lead or the Director sits alone,
 * the team is the Lead plus at most five agents, and a refusal is worded as the API answered.
 */
import type { Event, Layout } from "@tilo/contracts";
import { expect, test, vi } from "vitest";
import { villageBasicLayout } from "../../../../test-support/worldFixtures";
import { TiloApiError } from "../../../api/http";
import {
  ROOM_MAX_AGENTS,
  adjournRoom,
  askTurn,
  conveneRoom,
  roomFault,
  seatFor,
  teamSeat,
} from "./roomTalk";

const layout = villageBasicLayout() as unknown as Layout;
const events = [
  { actor: "A_l1", target: "A_s1", district: "D1", seq: 1 },
  { actor: "A_l1", target: "A_s2", district: "D1", seq: 2 },
] as unknown as Event[];

test("FR-HIL-09 TILO-T-WORLD room: a worker talks with its district's Lead in the room, one agent invited", () => {
  expect(seatFor(layout, events, "A_s1")).toEqual({ lead: "A_l1", agents: ["A_s1"] });
});

test("FR-HIL-09 TILO-T-WORLD room: a Lead or the Director talks alone (MR-02)", () => {
  expect(seatFor(layout, events, "A_l1")).toEqual({ lead: "A_l1", agents: [] });
  expect(seatFor(layout, events, "A_dir")).toEqual({ lead: "A_dir", agents: [] });
});

test("FR-HIL-09 TILO-T-WORLD room: an agent the layout does not hold, or a worker with no recorded district, has no seat", () => {
  expect(seatFor(layout, events, "A_ghost")).toBeNull();
  expect(seatFor(layout, [], "A_s1")).toBeNull();
});

test("FR-HIL-09 TILO-T-WORLD room: a team is its district's Lead plus the workers, capped at the room's size", () => {
  const seat = teamSeat(layout, events, "A_l1", ["A_s1", "A_s2", "A_v1"]);
  expect(seat?.lead).toBe("A_l1");
  expect(seat?.agents).toEqual(["A_s1", "A_s2"]); // A_v1 has no recorded district: not seated
  expect((seat?.agents.length ?? 0) <= ROOM_MAX_AGENTS).toBe(true);
});

test("FR-HIL-09 TILO-T-WORLD room: conveneRoom posts the lead and agents to the existing rooms route", async () => {
  const postJson = vi.fn().mockResolvedValue(roomBody());
  const room = await conveneRoom({ getJson: vi.fn(), postJson }, "w_1", {
    lead: "A_l1",
    agents: ["A_s1"],
  });
  expect(postJson).toHaveBeenCalledWith("/v1/worlds/w_1/rooms", { lead: "A_l1", agents: ["A_s1"] });
  expect(room.room_id).toBe("01ARZ3NDEKTSV4RRFFQ69G5FAV");
});

test("FR-HIL-09 TILO-T-WORLD room: askTurn posts the turn and reads the room back", async () => {
  const postJson = vi.fn().mockResolvedValue({});
  const getJson = vi.fn().mockResolvedValue(roomBody());
  await askTurn(
    { getJson, postJson },
    "w_1",
    "01ARZ3NDEKTSV4RRFFQ69G5FAV",
    "A_s1",
    "quick",
    "What did you find?",
  );
  expect(postJson).toHaveBeenCalledWith("/v1/worlds/w_1/rooms/01ARZ3NDEKTSV4RRFFQ69G5FAV/turns", {
    to: "A_s1",
    mode: "quick",
    text: "What did you find?",
  });
  expect(getJson).toHaveBeenCalledWith("/v1/worlds/w_1/rooms/01ARZ3NDEKTSV4RRFFQ69G5FAV");
});

test("FR-HIL-09 TILO-T-WORLD room: adjournRoom posts to the existing adjourn route", async () => {
  const postJson = vi
    .fn()
    .mockResolvedValue({ ...roomBody(), state: "adjourned", reason: "person" });
  await adjournRoom({ getJson: vi.fn(), postJson }, "w_1", "01ARZ3NDEKTSV4RRFFQ69G5FAV");
  expect(postJson).toHaveBeenCalledWith(
    "/v1/worlds/w_1/rooms/01ARZ3NDEKTSV4RRFFQ69G5FAV/adjourn",
    {},
  );
});

test("FR-HIL-09 TILO-T-WORLD room: a 503 not_configured says the rooms are not switched on, never a guess", () => {
  const e = new TiloApiError("x", 503, false, true, "not_configured");
  expect(roomFault(e)).toMatch(/not switched on|not configured/i);
  expect(roomFault(new TiloApiError("x", 409, false, true, "room_open"))).toMatch(/already open/i);
  expect(roomFault(new TiloApiError("x", 409, false, true, "world_paused"))).toMatch(/paused/i);
  expect(roomFault(new TiloApiError("x", 404, false, true))).toMatch(/not found|access/i);
  expect(roomFault(new Error("boom"))).toMatch(/could not/i);
});

function roomBody() {
  return {
    room_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
    world_id: "w_1",
    run_id: "r_1",
    state: "open",
    reason: null,
    lead: "A_l1",
    agents: ["A_s1"],
    as_role: "owner",
    credit_cap: 20,
    credits_spent: 0,
    max_turns: 20,
    turns: [],
  };
}
