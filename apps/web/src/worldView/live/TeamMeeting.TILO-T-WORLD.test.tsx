// @vitest-environment happy-dom
/**
 * TILO-T-WORLD step 4 (ADR-0028, MR-02, MR-07): "Convene team" calls a Lead and the agents it can seat into the
 * Meeting Hall through the existing room route, at once (the stage walks them in on meeting.convened); a question can be
 * "change direction"; an already-open room of the person's is closed first; a refusal is worded as the API answered.
 */
import type { Layout } from "@tilo/contracts";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../test-support/park/componentsHarness";
import { villageBasicLayout } from "../../../test-support/worldFixtures";
import { ev, fakeWorld, resetEvents, withClient } from "../../../test-support/worldLive";
import { TiloApiError } from "../../api/http";
import type { RoomClient } from "../../park/api/live/meetingHall";
import { resetSpotlights } from "../../world/spotlight";
import { AgentLayer } from "./AgentLayer";

afterEach(() => {
  cleanup();
  resetSpotlights();
});

const layout = villageBasicLayout() as unknown as Layout;
const ROOM = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const room = (extra: object = {}) => ({
  room_id: ROOM,
  world_id: "w_live",
  run_id: "r_live",
  state: "open",
  reason: null,
  lead: "A_l1",
  agents: ["A_s1", "A_s2"],
  as_role: "owner",
  credit_cap: 20,
  credits_spent: 0,
  max_turns: 20,
  turns: [] as unknown[],
  ...extra,
});
const base = () => {
  resetEvents();
  return [
    ev("agent.moved", "A_l1", "B1", { from: "B1" }),
    ev("agent.assigned", "A_l1", "A_s1", { unit: "U1" }),
    ev("agent.assigned", "A_l1", "A_s2", { unit: "U2" }),
  ];
};

const settle = () =>
  act(async () => {
    for (let i = 0; i < 4; i++) await Promise.resolve();
  });

function rig(initial = base(), postJson?: RoomClient["postJson"]) {
  const calls: [string, unknown][] = [];
  const client: RoomClient = {
    getJson: vi.fn(async () => room()),
    postJson:
      postJson ??
      vi.fn(async (path: string, body: unknown) => {
        calls.push([path, body]);
        if (path.endsWith("/turns")) return {};
        return room();
      }),
  };
  const world = fakeWorld(layout, initial);
  return { client, calls, world };
}

async function open(r: ReturnType<typeof rig>) {
  const m = mount(withClient(r.world.client, <AgentLayer worldId="w_live" rooms={r.client} />));
  await settle();
  click(m.container.querySelector(".tw-convene") as Element);
  await settle();
  return m;
}
const submit = (form: HTMLFormElement) =>
  act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
const check = (box: HTMLInputElement) => click(box);

describe("TILO-T-WORLD team meeting", () => {
  it("offers only the agents the API would seat with the Lead, and convenes at once with the chosen ones", async () => {
    const r = rig();
    const m = await open(r);
    const boxes = [...m.container.querySelectorAll<HTMLInputElement>(".tw-team__pick input")];
    expect(boxes).toHaveLength(2); // A_s1 and A_s2; A_v1 has no recorded district, so no seat
    for (const b of boxes) check(b);
    await submit(m.container.querySelector(".tw-team__form") as HTMLFormElement);
    await settle();
    expect(r.calls).toEqual([
      ["/v1/worlds/w_live/rooms", { lead: "A_l1", agents: ["A_s1", "A_s2"] }],
    ]);
    expect(m.container.textContent).toContain("Team meeting");
  });

  it("'Ask them to change direction' puts a thinking-mode ask in the composer and sends it to the room", async () => {
    const r = rig();
    const m = await open(r);
    await submit(m.container.querySelector(".tw-team__form") as HTMLFormElement);
    await settle();
    const ask = [...m.container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("change direction"),
    );
    click(ask as Element);
    const box = m.container.querySelector(
      "textarea[aria-label='Your question']",
    ) as HTMLTextAreaElement;
    expect(box.value).toMatch(/different direction/);
    const mode = [...m.container.querySelectorAll<HTMLSelectElement>(".tw-room__form select")].at(
      -1,
    );
    expect(mode?.value).toBe("thinking");
    await submit(m.container.querySelector(".tw-room__form") as HTMLFormElement);
    await settle();
    const turn = r.calls.find(([p]) => p.endsWith("/turns"));
    expect(turn?.[1]).toMatchObject({ mode: "thinking" });
    expect(String((turn?.[1] as { text: string }).text)).toMatch(/different direction/);
  });

  it("an open room of the person's own is closed first when the world allows one room at a time", async () => {
    const events = [
      ...base(),
      ev("meeting.convened", "u_owner", "A_l1", { room_id: ROOM, lead: "A_l1", agents: [] }),
    ];
    const calls: string[] = [];
    let refused = false;
    const r = rig(
      events,
      vi.fn(async (path: string) => {
        calls.push(path);
        if (path.endsWith("/rooms") && !refused) {
          refused = true;
          throw new TiloApiError("x", 409, false, true, "room_open");
        }
        return path.endsWith("/adjourn") ? room({ state: "adjourned", reason: "person" }) : room();
      }),
    );
    const m = await open(r);
    await submit(m.container.querySelector(".tw-team__form") as HTMLFormElement);
    await settle();
    expect(calls).toEqual([
      "/v1/worlds/w_live/rooms",
      `/v1/worlds/w_live/rooms/${ROOM}/adjourn`,
      "/v1/worlds/w_live/rooms",
    ]);
  });

  it("a paused world's refusal is shown in words and no meeting is claimed", async () => {
    const r = rig(
      base(),
      vi.fn(async () => {
        throw new TiloApiError("x", 409, false, true, "world_paused");
      }),
    );
    const m = await open(r);
    await submit(m.container.querySelector(".tw-team__form") as HTMLFormElement);
    await settle();
    expect(m.container.querySelector(".tw-room__err")?.textContent).toMatch(/paused/i);
  });

  it("without a room client the Convene button is off and says why", async () => {
    const world = fakeWorld(layout, base());
    const m = mount(withClient(world.client, <AgentLayer worldId="w_live" rooms={null} />));
    await settle();
    click(m.container.querySelector(".tw-convene") as Element);
    await settle();
    expect((m.container.querySelector(".tw-team__go") as HTMLButtonElement).disabled).toBe(true);
    expect(m.container.textContent).toContain("not connected");
  });
});
