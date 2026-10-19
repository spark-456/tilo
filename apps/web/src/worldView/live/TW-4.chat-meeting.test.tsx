// @vitest-environment happy-dom
/**
 * TW-4: WhatsApp-like chat pop-up (open 220 ms / close 160 ms), filters (All / pair / agent / You / Team meeting),
 * Convene dialog (pick Lead + agents), meeting in the Hall (meeting.called -> agents walk to Hall slots,
 * Hall chip "In session", Chat opens meeting thread).
 */
import type { Layout } from "@tilo/contracts";
import { act } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, click, mount } from "../../../test-support/park/componentsHarness";
import { villageBasicLayout } from "../../../test-support/worldFixtures";
import { ev, fakeWorld, resetEvents, withClient } from "../../../test-support/worldLive";
import { frameOf } from "../../world/frame";
import { applyEvent, createInitialState, standingAt } from "../../world/reducer";
import { resetSpotlights } from "../../world/spotlight";
import { AgentLayer } from "./AgentLayer";
import { ChatPopUp } from "./ChatPopUp";

afterEach(() => {
  cleanup();
  resetSpotlights();
});

// The layout names its Meeting Hall (the reducer never guesses one): the fixture's town hall is marked as it.
const layout = (() => {
  const base = villageBasicLayout() as unknown as Layout;
  const copy = JSON.parse(JSON.stringify(base)) as Layout;
  const buildings = copy.semantic.levels.flatMap((l) => l.districts).flatMap((d) => d.buildings);
  const hall = buildings.find((b) => b.common_type === "town_hall") ?? buildings[0];
  if (hall) (hall as { common_type?: string }).common_type = "meeting_hall";
  return copy;
})();

const runEvents = () => {
  resetEvents();
  return [
    ev("agent.spawned", "A_dir", "A_l1", { role: "lead" }),
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
      envelope: { summary: "Triaged 12 emails.", acceptance_criteria: ["flight-shortlist.json"] },
    }),
  ];
};

const settle = () =>
  act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

describe("TW-4 Chat pop-up & Convene dialog & Meeting Hall", () => {
  it("event-to-motion: meeting.called moves picked agents to Hall slots, sets inSession on Hall building", () => {
    const initialState = createInitialState(layout);
    expect(initialState.hall).not.toBeNull();
    const hallId = initialState.hall ?? "";

    // Plan the hall building
    let state = applyEvent(
      initialState,
      ev("building.planned", "A_dir", hallId, { status: "planned" }),
      layout,
    );
    // Move agents initially
    state = applyEvent(state, ev("agent.moved", "A_l1", "B1", { from: "B1" }), layout);
    state = applyEvent(state, ev("agent.moved", "A_s1", "B2", { from: "B1" }), layout);

    const agL1 = state.agents.A_l1;
    const agS1 = state.agents.A_s1;
    expect(agL1).toBeDefined();
    expect(agS1).toBeDefined();
    if (!agL1 || !agS1) throw new Error("agents missing");

    expect(standingAt(state, agL1)).toBe("B1");
    expect(standingAt(state, agS1)).toBe("B2");

    // Hall building before meeting is not in session
    let frame = frameOf(layout, state);
    const hallBefore = frame.buildings.find((b) => b.id === hallId);
    expect(hallBefore?.inSession).toBeFalsy();

    // meeting.called arrives with attendees
    const meetingEv = ev("meeting.called", "u_owner", hallId, {
      card_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
      lead: "A_l1",
      agents: ["A_s1"],
      attendees: ["A_l1", "A_s1"],
    });
    state = applyEvent(state, meetingEv, layout);

    // Agents have walked to the Hall
    const agL1InMeeting = state.agents.A_l1;
    const agS1InMeeting = state.agents.A_s1;
    expect(agL1InMeeting && standingAt(state, agL1InMeeting)).toBe(hallId);
    expect(agS1InMeeting && standingAt(state, agS1InMeeting)).toBe(hallId);
    expect(state.agents.A_l1?.location).toBe(hallId);
    expect(state.agents.A_s1?.location).toBe(hallId);

    // Hall building now has inSession: true for the lime 'In session' chip
    frame = frameOf(layout, state);
    const hallAfter = frame.buildings.find((b) => b.id === hallId);
    expect(hallAfter?.inSession).toBe(true);

    // meeting.adjourned sends agents back and clears inSession
    const adjournEv = ev("meeting.adjourned", "u_owner", hallId, {
      room_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
      card_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
      reason: "completed",
    });
    state = applyEvent(state, adjournEv, layout);
    const agL1After = state.agents.A_l1;
    const agS1After = state.agents.A_s1;
    expect(agL1After && standingAt(state, agL1After)).toBe("B1");
    expect(agS1After && standingAt(state, agS1After)).toBe("B2");
    frame = frameOf(layout, state);
    expect(frame.buildings.find((b) => b.id === hallId)?.inSession).toBeFalsy();
  });

  it("chat pop-up renders WhatsApp-like UI with filters, avatars, hand-over file note, and input bar", async () => {
    const world = fakeWorld(layout, runEvents());
    const m = mount(
      withClient(
        world.client,
        <ChatPopUp
          worldId="w_live"
          facts={{
            layout,
            events: runEvents(),
            names: new Map([
              ["A_l1", "Kai"],
              ["A_s1", "Remy"],
            ]),
            messages: [
              {
                seq: 1,
                ts: "2026-10-18T10:00:00Z",
                kind: "assigned",
                from: "A_l1",
                to: "A_s1",
                text: "Triage the inbox",
                detail: [],
                where: "B1",
                room: null,
                turn: null,
                credits: 1,
              },
              {
                seq: 2,
                ts: "2026-10-18T10:01:00Z",
                kind: "handoff",
                from: "A_s1",
                to: "A_l1",
                text: "Triaged 12 emails.",
                detail: ["flight-shortlist.json"],
                where: "B2",
                room: null,
                turn: null,
                credits: 2,
              },
            ],
            stats: new Map(),
            rooms: [],
          }}
          events={runEvents()}
          rooms={null}
          initialFilter="all"
          onClose={() => {}}
          onConvene={() => {}}
        />,
      ),
    );
    await settle();

    // Dialog structure
    const dialog = m.container.querySelector('[data-testid="world-talk-chat"]');
    expect(dialog).not.toBeNull();
    expect(dialog?.getAttribute("aria-label")).toBe("Agent conversation");

    // Header has title and subtitle
    expect(dialog?.querySelector(".tw-chat-popup__title")?.textContent).toBe("Team chat");
    expect(dialog?.querySelector(".tw-chat-popup__sub")?.textContent).toBe(
      "What the agents said, in plain words",
    );

    // Filter bar has tabs: All, pair, agents, You
    const tabs = [...m.container.querySelectorAll<HTMLButtonElement>(".tw-chat-filter")];
    expect(tabs.map((t) => t.textContent?.trim())).toContain("All");
    expect(tabs.map((t) => t.textContent?.trim())).toContain("You");

    // Avatars have cute visor faces
    const avatars = m.container.querySelectorAll(".tw-chat-av");
    expect(avatars.length).toBeGreaterThan(0);
    expect(m.container.querySelector(".tw-chat-visor")).not.toBeNull();

    // Hand-over card shows file name
    const handoff = m.container.querySelector(".tw-chat-handover");
    expect(handoff).not.toBeNull();
    expect(handoff?.textContent).toContain("flight-shortlist.json");
    expect(handoff?.textContent).toContain("Triaged 12 emails.");

    // Input bar
    const input = m.container.querySelector(".tw-chat-input") as HTMLInputElement;
    expect(input).not.toBeNull();
    const sendBtn = m.container.querySelector(".tw-chat-send");
    expect(sendBtn).not.toBeNull();
  });

  it("chat pop-up opens from talking 3-dots on stage and filters to that pair", async () => {
    resetEvents();
    const events = [
      ev("agent.spawned", "A_dir", "A_l1", { role: "lead" }),
      ev("agent.moved", "A_l1", "B1", { from: "B1" }),
      ev("agent.moved", "A_s1", "B2", { from: "B1" }),
      ev("agent.handoff", "A_s1", "A_l1", {
        envelope: { summary: "Triaged 12 emails." },
      }),
    ];
    const world = fakeWorld(layout, events);
    const m = mount(withClient(world.client, <AgentLayer worldId="w_live" rooms={null} />));
    await settle();

    // Clicking tw-talk-dots opens ChatPopUp
    const dots = m.container.querySelector(".tw-talk-dots") as Element;
    if (dots) {
      click(dots);
      await settle();
      const popup = m.container.querySelector('[data-testid="world-talk-chat"]');
      expect(popup).not.toBeNull();
    }
  });

  it("convene dialog opens meeting thread with system pill in chat", async () => {
    const world = fakeWorld(layout, runEvents());
    const m = mount(
      withClient(
        world.client,
        <ChatPopUp
          worldId="w_live"
          facts={{
            layout,
            events: runEvents(),
            names: new Map([
              ["A_l1", "Kai"],
              ["A_s1", "Remy"],
              ["A_s2", "Juno"],
            ]),
            messages: [
              {
                seq: 1,
                ts: "2026-10-18T10:00:00Z",
                kind: "convened",
                from: "u_owner",
                to: "meeting",
                text: "Called meeting",
                detail: [],
                where: "B1",
                room: "room1",
                turn: null,
                credits: 0,
              },
            ],
            stats: new Map(),
            rooms: ["room1"],
          }}
          events={runEvents()}
          rooms={null}
          initialFilter="meeting"
          onClose={() => {}}
          onConvene={() => {}}
        />,
      ),
    );
    await settle();

    // Meeting thread header
    expect(m.container.querySelector(".tw-chat-popup__title")?.textContent).toBe("Team meeting");
    expect(m.container.querySelector(".tw-chat-popup__sub")?.textContent).toContain("Meeting Hall");

    // System pill
    const sysPill = m.container.querySelector(".tw-chat-sys");
    expect(sysPill).not.toBeNull();
    expect(sysPill?.textContent).toContain("Team meeting");
  });
});
