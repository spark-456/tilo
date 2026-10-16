// @vitest-environment happy-dom
/**
 * TILO-T-WORLD step 6 (HR-1, PRD 9.4, design PROMPT section 3): confetti bursts once on world.completed, a parcel arcs
 * on artifact.delivered, a failed world says why and what it did not do. Each starts only for an event that ARRIVES while
 * the page is open; history already recorded when the stage opens is shown, not celebrated. The "nothing was booked"
 * line is claimed only when the record has no approved or sent action.
 */
import type { Layout } from "@tilo/contracts";
import { act } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { villageBasicLayout } from "../../../test-support/worldFixtures";
import { ev, fakeWorld, resetEvents, withClient } from "../../../test-support/worldLive";
import { registerProbe, resetSpotlights } from "../../world/spotlight";
import { AgentLayer } from "./AgentLayer";
import { failureNote } from "./StageEvents";

afterEach(() => {
  cleanup();
  resetSpotlights();
});

const layout = structuredClone(villageBasicLayout()) as unknown as Layout;
for (const b of layout.semantic.levels[0]?.districts[0]?.buildings ?? []) {
  if (b.id === "B3") (b as { common_type?: string }).common_type = "meeting_hall";
  if (b.id === "B4") (b as { common_type?: string }).common_type = "delivery_dock";
}
const settle = () =>
  act(async () => {
    for (let i = 0; i < 4; i++) await Promise.resolve();
  });

async function open(initial = [ev("world.started", "system", "w_live")]) {
  const world = fakeWorld(layout, initial);
  const m = mount(withClient(world.client, <AgentLayer worldId="w_live" rooms={null} />));
  await settle();
  return { m, world };
}

describe("TILO-T-WORLD stage moments", () => {
  it("confetti bursts once when world.completed arrives live", async () => {
    resetEvents();
    const { m, world } = await open();
    expect(m.container.querySelector('[data-testid="confetti"]')).toBeNull();
    act(() => world.push(ev("world.completed", "A_dir", "w_live")));
    await settle();
    expect(m.container.querySelector('[data-testid="confetti"]')?.children.length).toBeGreaterThan(
      10,
    );
  });

  it("a world that was already completed when the stage opened is lit, not celebrated again", async () => {
    resetEvents();
    const { m } = await open([ev("world.started", "s", "w"), ev("world.completed", "A_dir", "w")]);
    expect(m.container.querySelector('[data-testid="confetti"]')).toBeNull();
  });

  it("a parcel arcs from the Meeting Hall to the Delivery Dock when artifact.delivered arrives, if the stage can place both", async () => {
    resetEvents();
    const { m, world } = await open();
    registerProbe("w_live", {
      agentAt: () => null,
      locate: (id) => (id === "B3" ? { x: 10, y: 20 } : id === "B4" ? { x: 200, y: 120 } : null),
    });
    act(() => world.push(ev("artifact.delivered", "A_l1", "art_x")));
    await settle();
    const parcel = m.container.querySelector<HTMLElement>(".tw-parcel");
    expect(parcel).not.toBeNull();
    expect(parcel?.style.offsetPath).toContain("M 10 20 Q");
  });

  it("with no place for one end of the flight, no parcel is drawn", async () => {
    resetEvents();
    const { m, world } = await open();
    act(() => world.push(ev("artifact.delivered", "A_l1", "art_x")));
    await settle();
    expect(m.container.querySelector(".tw-parcel")).toBeNull();
  });

  it("a failed world gets a reason card with the event's words and an honest note on what it did", async () => {
    resetEvents();
    const { m } = await open([
      ev("world.started", "s", "w"),
      ev(
        "world.failed",
        "system",
        "w_live",
        {},
        { summary: "The booking site refused every request." },
      ),
    ]);
    const card = m.container.querySelector('[data-testid="world-failed-card"]');
    expect(card?.textContent).toContain("The booking site refused every request.");
    expect(card?.textContent).toContain("Nothing was booked, sent or paid.");
  });

  it("failureNote never claims nothing happened when an approved action or a sent message is on record", () => {
    resetEvents();
    const sent = failureNote([ev("channel.message_out", "A_l1", "u")]);
    expect(sent).toMatch(/1 approved action had already happened/);
    const approved = failureNote([
      ev("approval.resolved", "u_owner", "A_l1", { option: "approve" }),
      ev("channel.message_out", "A_l1", "u"),
    ]);
    expect(approved).toMatch(/2 approved actions/);
    expect(failureNote([ev("agent.moved", "A_l1", "B1")])).toBe(
      "Nothing was booked, sent or paid.",
    );
  });
});
