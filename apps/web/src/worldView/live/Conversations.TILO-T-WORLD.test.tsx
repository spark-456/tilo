// @vitest-environment happy-dom
/**
 * TILO-T-WORLD step 2 (FR-WLD-04, HR-1, MR-12): the Conversations chat shows every recorded message with its real words,
 * live as events arrive, filtered by agent or pair; a click flies the camera there and lights both agents; room turns
 * get their words from the archive and stay unworded when it has none.
 */
import type { Layout } from "@tilo/contracts";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../test-support/park/componentsHarness";
import { villageBasicLayout } from "../../../test-support/worldFixtures";
import { ev, fakeWorld, resetEvents, withClient } from "../../../test-support/worldLive";
import type { RoomClient } from "../../park/api/live/meetingHall";
import { getSelection } from "../../world/selection";
import { getSpotlight, onFly, resetSpotlights } from "../../world/spotlight";
import { Conversations } from "./Conversations";

afterEach(() => {
  cleanup();
  resetSpotlights();
});

const layout = villageBasicLayout() as unknown as Layout;
const run = () => {
  resetEvents();
  return [
    ev("agent.moved", "A_l1", "B1", { from: "B1" }),
    ev(
      "agent.assigned",
      "A_l1",
      "A_s1",
      { unit: "U1" },
      { summary: "The Lead gave it: Triage the inbox" },
    ),
    ev("agent.moved", "A_s1", "B2", { from: "B1" }),
    ev("agent.handoff", "A_s1", "A_l1", {
      envelope: { summary: "Triaged 12 emails.", acceptance_criteria: ["One category each"] },
    }),
  ];
};

const settle = () =>
  act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

async function open(rooms: RoomClient | null = null) {
  const world = fakeWorld(layout, run());
  const m = mount(withClient(world.client, <Conversations worldId="w_live" rooms={rooms} />));
  await settle();
  return { m, world };
}

const rows = (el: HTMLElement) => [...el.querySelectorAll<HTMLElement>(".tw-msg")];

describe("TILO-T-WORLD Conversations", () => {
  it("lists each recorded message with who said it to whom and the real words, in order", async () => {
    const { m } = await open();
    const list = rows(m.container);
    expect(list.map((r) => r.dataset.kind)).toEqual(["assigned", "handoff"]);
    expect(list[0]?.textContent).toContain("Lead");
    expect(list[0]?.textContent).toContain("Specialist 1");
    expect(list[0]?.textContent).toContain("The Lead gave it: Triage the inbox");
    expect(list[1]?.textContent).toContain("Triaged 12 emails.");
    expect(list[1]?.textContent).toContain("One category each");
  });

  it("appends a message live when its event arrives", async () => {
    const { m, world } = await open();
    act(() =>
      world.push(ev("agent.help_requested", "A_s2", "A_l1", {}, { summary: "Which thread?" })),
    );
    await settle();
    const last = rows(m.container).at(-1);
    expect(last?.dataset.kind).toBe("help");
    expect(last?.textContent).toContain("Which thread?");
  });

  it("filters by agent and by pair", async () => {
    const { m, world } = await open();
    act(() =>
      world.push(ev("agent.help_requested", "A_s2", "A_l1", {}, { summary: "Which thread?" })),
    );
    await settle();
    const [agent, other] = [...m.container.querySelectorAll("select")] as HTMLSelectElement[];
    const set = (s: HTMLSelectElement, v: string) =>
      act(() => {
        s.value = v;
        s.dispatchEvent(new Event("change", { bubbles: true }));
      });
    set(agent as HTMLSelectElement, "A_s2");
    expect(rows(m.container)).toHaveLength(1);
    set(agent as HTMLSelectElement, "A_l1");
    set(other as HTMLSelectElement, "A_s1");
    expect(rows(m.container).map((r) => r.dataset.kind)).toEqual(["assigned", "handoff"]);
  });

  it("a click flies the camera to where it happened and lights both speakers", async () => {
    const { m } = await open();
    const fly = vi.fn();
    const off = onFly("w_live", fly);
    click(rows(m.container)[1]?.querySelector("button") as Element);
    expect(fly).toHaveBeenCalledWith("B2", 900);
    expect(getSpotlight("w_live").lit).toEqual(["A_s1", "A_l1"]);
    expect(getSelection("w_live")).toBe("A_s1");
    off();
  });

  it("says plainly when nothing has been said yet", async () => {
    resetEvents();
    const world = fakeWorld(layout, []);
    const m = mount(withClient(world.client, <Conversations worldId="w_live" rooms={null} />));
    await settle();
    expect(m.container.textContent).toContain("No conversations yet");
  });

  it("a room turn shows the archive's words, and says they are unavailable when the room cannot be read", async () => {
    const turns = [
      ev("meeting.convened", "u_owner", "A_l1", {
        room_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        lead: "A_l1",
        agents: ["A_s1"],
      }),
      ev("meeting.asked", "u_owner", "A_s1", {
        room_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        turn: 1,
        to: "A_s1",
        mode: "quick",
      }),
    ];
    const world = fakeWorld(layout, turns);
    const room = {
      room_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
      world_id: "w_live",
      run_id: "r_live",
      state: "open",
      reason: null,
      lead: "A_l1",
      agents: ["A_s1"],
      as_role: "owner",
      credit_cap: 20,
      credits_spent: 0,
      max_turns: 20,
      turns: [
        {
          turn: 1,
          to: "A_s1",
          mode: "quick",
          text: "What did you find?",
          reply: null,
          change: null,
        },
      ],
    };
    const rooms: RoomClient = { getJson: vi.fn().mockResolvedValue(room), postJson: vi.fn() };
    const m = mount(withClient(world.client, <Conversations worldId="w_live" rooms={rooms} />));
    await settle();
    await settle();
    expect(m.container.textContent).toContain("What did you find?");
    cleanup();
    const bare = mount(
      withClient(fakeWorld(layout, turns).client, <Conversations worldId="w_live" rooms={null} />),
    );
    await settle();
    expect(bare.container.textContent).toContain("not available to show");
  });
});
