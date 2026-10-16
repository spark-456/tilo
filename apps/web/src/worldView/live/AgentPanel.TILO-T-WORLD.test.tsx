// @vitest-environment happy-dom
/**
 * TILO-T-WORLD step 3 (FR-HIL-09, MR-02, MR-07, MR-11): clicking an agent opens its panel; "Talk to <agent>" is a 1:1
 * room through the existing routes, convened only when the first question is sent; the reply is the API's, a proposed
 * change needs the person's confirmation and its outcome is shown as the API gave it; a refusal is worded, never faked.
 */
import type { Layout } from "@tilo/contracts";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../test-support/park/componentsHarness";
import { villageBasicLayout } from "../../../test-support/worldFixtures";
import { ev, fakeWorld, resetEvents, withClient } from "../../../test-support/worldLive";
import { TiloApiError } from "../../api/http";
import type { RoomClient } from "../../park/api/live/meetingHall";
import { openAgent, resetSpotlights } from "../../world/spotlight";
import { AgentLayer } from "./AgentLayer";

afterEach(() => {
  cleanup();
  resetSpotlights();
});

const layout = villageBasicLayout() as unknown as Layout;
const ROOM = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const PROPOSAL = "01ARZ3NDEKTSV4RRFFQ69G5FAW";
const events = () => {
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
    ev("agent.handoff", "A_s1", "A_l1", { envelope: { summary: "Triaged 12 emails." } }),
  ];
};

const baseRoom = {
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
  turns: [] as unknown[],
};

function roomClient(opts: { propose?: boolean; refuse?: TiloApiError } = {}) {
  let room = { ...baseRoom };
  const calls: [string, unknown][] = [];
  const client: RoomClient = {
    getJson: vi.fn(async () => room),
    postJson: vi.fn(async (path: string, body: unknown) => {
      calls.push([path, body]);
      if (opts.refuse) throw opts.refuse;
      if (path.endsWith("/turns")) {
        const b = body as { to: string; text: string };
        room = {
          ...room,
          credits_spent: 0.4,
          turns: [
            {
              turn: 1,
              to: b.to,
              mode: "quick",
              text: b.text,
              reply: {
                from: b.to,
                outcome: opts.propose ? "proposed_change" : "answered",
                text: "I triaged 12 emails into five categories.",
                units: ["U1"],
                artifacts: [],
                proposal: opts.propose
                  ? { proposal_id: PROPOSAL, units: ["U1"], artifacts: [] }
                  : null,
              },
              change: null,
            },
          ],
        };
        return {};
      }
      if (path.endsWith("/changes")) return { proposal_id: PROPOSAL, planning: "started" };
      if (path.endsWith("/adjourn")) return { ...room, state: "adjourned", reason: "person" };
      return room;
    }),
  };
  return { client, calls };
}

const settle = () =>
  act(async () => {
    for (let i = 0; i < 4; i++) await Promise.resolve();
  });

async function openPanel(rooms: RoomClient | null, agent = "A_s1") {
  const world = fakeWorld(layout, events());
  const m = mount(withClient(world.client, <AgentLayer worldId="w_live" rooms={rooms} />));
  await settle();
  act(() => openAgent("w_live", agent));
  await settle();
  return m;
}

const type = (el: HTMLTextAreaElement, value: string) =>
  act(() => {
    const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
    set?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
const submit = (form: HTMLFormElement) =>
  act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });

describe("TILO-T-WORLD agent panel", () => {
  it("opens with the agent's recorded facts and what it remembers, and convenes nothing yet", async () => {
    const { client, calls } = roomClient();
    const m = await openPanel(client);
    const panel = m.container.querySelector('[data-testid="agent-panel"]');
    const text = panel?.textContent ?? "";
    expect(text).toContain("Specialist 1");
    expect(text).toContain("Talk to Specialist 1");
    expect(text).toContain("Triaged 12 emails.");
    expect(text).toContain("The Lead gave it: Triage the inbox");
    expect(calls).toEqual([]);
  });

  it("the first question convenes a 1:1 room (the district Lead plus this agent), asks, and shows the reply", async () => {
    const { client, calls } = roomClient();
    const m = await openPanel(client);
    type(
      m.container.querySelector("textarea[aria-label='Your question']") as HTMLTextAreaElement,
      "What did you do?",
    );
    await submit(m.container.querySelector(".tw-room__form") as HTMLFormElement);
    await settle();
    expect(calls.map(([p]) => p)).toEqual([
      "/v1/worlds/w_live/rooms",
      `/v1/worlds/w_live/rooms/${ROOM}/turns`,
    ]);
    expect(calls[0]?.[1]).toEqual({ lead: "A_l1", agents: ["A_s1"] });
    expect(calls[1]?.[1]).toEqual({ to: "A_s1", mode: "quick", text: "What did you do?" });
    const text = m.container.textContent ?? "";
    expect(text).toContain("I triaged 12 emails into five categories.");
    expect(text).toContain("Cites U1");
    expect(text).toContain("0.4 of 20 credits");
  });

  it("a proposed change is confirmed by the person and its outcome shown as the API gave it", async () => {
    const { client, calls } = roomClient({ propose: true });
    const m = await openPanel(client);
    type(
      m.container.querySelector("textarea[aria-label='Your question']") as HTMLTextAreaElement,
      "Change course?",
    );
    await submit(m.container.querySelector(".tw-room__form") as HTMLFormElement);
    await settle();
    expect(m.container.textContent).toContain("proposes a change to U1");
    await submit(m.container.querySelector(".tw-room__change") as HTMLFormElement);
    await settle();
    const change = calls.find(([p]) => p.endsWith("/changes"));
    expect(change?.[1]).toEqual({ proposal_id: PROPOSAL, text: "Go ahead with this change." });
    expect(m.container.textContent).toContain("accepted: the planner has started on it");
  });

  it("a 503 not configured says rooms are not switched on and shows no made-up reply", async () => {
    const { client } = roomClient({
      refuse: new TiloApiError("x", 503, false, true, "not_configured"),
    });
    const m = await openPanel(client);
    type(
      m.container.querySelector("textarea[aria-label='Your question']") as HTMLTextAreaElement,
      "Hello?",
    );
    await submit(m.container.querySelector(".tw-room__form") as HTMLFormElement);
    await settle();
    expect(m.container.querySelector(".tw-room__err")?.textContent).toMatch(/not switched on/i);
    expect(m.container.querySelector(".tw-bubble")).toBeNull();
  });

  it("with no room client it says nothing was asked, and a Lead is talked to alone", async () => {
    const m = await openPanel(null);
    expect(m.container.textContent).toContain("needs the live Tilo service");
    cleanup();
    const { client, calls } = roomClient();
    const lead = await openPanel(client, "A_l1");
    type(
      lead.container.querySelector("textarea[aria-label='Your question']") as HTMLTextAreaElement,
      "Status?",
    );
    await submit(lead.container.querySelector(".tw-room__form") as HTMLFormElement);
    await settle();
    expect(calls[0]?.[1]).toEqual({ lead: "A_l1", agents: [] });
  });

  it("close puts the panel away", async () => {
    const { client } = roomClient();
    const m = await openPanel(client);
    click(m.container.querySelector("button[aria-label='Close']") as Element);
    expect(m.container.querySelector('[data-testid="agent-panel"]')).toBeNull();
  });
});
