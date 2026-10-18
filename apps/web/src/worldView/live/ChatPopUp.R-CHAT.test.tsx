// @vitest-environment happy-dom
import type { Layout, MeetingRoom } from "@tilo/contracts";
import { act } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, click, mount } from "../../../test-support/park/componentsHarness";
import { villageBasicLayout } from "../../../test-support/worldFixtures";
import { ev, resetEvents } from "../../../test-support/worldLive";
import type { RoomClient } from "../../park/api/live/meetingHall";
import { ChatPopUp } from "./ChatPopUp";

afterEach(cleanup);
const ROOM = "01ARZ3NDEKTSV4RRFFQ69G5FAV";

const settle = () =>
  act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });

function room(turns: MeetingRoom["turns"] = []): MeetingRoom {
  return {
    room_id: ROOM,
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
    turns,
  };
}

describe("R-CHAT world chat", () => {
  it("R_CHAT_popup_sends_through_the_room_route_and_shows_bubbles_and_typing", async () => {
    resetEvents();
    const events = [
      ev("agent.spawned", "A_dir", "A_l1", { role: "lead" }),
      ev("agent.spawned", "A_l1", "A_s1", { role: "specialist" }, { district: "D1" }),
    ];
    let release: ((value: MeetingRoom) => void) | undefined;
    const answer = new Promise<MeetingRoom>((resolve) => {
      release = resolve;
    });
    const calls: Array<{ path: string; body?: unknown }> = [];
    const client: RoomClient = {
      getJson: async (path) => {
        calls.push({ path });
        return answer;
      },
      postJson: async (path, body) => {
        calls.push({ path, body });
        return path.endsWith("/turns") ? {} : room();
      },
    };
    const layout = villageBasicLayout() as unknown as Layout;
    const m = mount(
      <ChatPopUp
        worldId="w_live"
        facts={{
          layout,
          events,
          names: new Map([
            ["A_l1", "Kai"],
            ["A_s1", "Remy"],
          ]),
          messages: [],
          stats: new Map(),
          rooms: [],
        }}
        events={events}
        rooms={client}
        initialFilter="agent:A_s1"
        onClose={() => {}}
        onConvene={() => {}}
      />,
    );
    const input = m.container.querySelector<HTMLInputElement>(".tw-chat-input");
    if (!input) throw new Error("chat input missing");
    expect(input.disabled).toBe(false);
    act(() => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      set?.call(input, "What did you finish?");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    click(m.container.querySelector(".tw-chat-send") as Element);
    await settle();

    expect(calls.map((call) => call.path)).toEqual([
      "/v1/worlds/w_live/rooms",
      `/v1/worlds/w_live/rooms/${ROOM}/turns`,
      `/v1/worlds/w_live/rooms/${ROOM}`,
    ]);
    expect(m.container.querySelector(".tw-chat-bubble--pending")?.textContent).toContain(
      "What did you finish?",
    );
    expect(m.container.querySelector(".tw-chat-typing")?.textContent).toContain(
      "Remy is answering",
    );

    await act(async () => {
      release?.(
        room([
          {
            turn: 1,
            to: "A_s1",
            mode: "quick",
            text: "What did you finish?",
            reply: {
              from: "A_s1",
              outcome: "answered",
              text: "I finished the recorded inbox step.",
              units: ["U1"],
              artifacts: [],
              proposal: null,
            },
            change: null,
          },
        ]),
      );
      await answer;
      await Promise.resolve();
    });
    expect(m.container.textContent).toContain("I finished the recorded inbox step.");
    expect(m.container.querySelector(".tw-chat-typing")).toBeNull();
  });
});
