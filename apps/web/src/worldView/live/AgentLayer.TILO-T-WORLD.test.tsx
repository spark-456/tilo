// @vitest-environment happy-dom
/**
 * TILO-T-WORLD step 3 (FR-WLD-06, HR-1): hovering an agent shows its stats card, every figure in it read from the
 * recorded events: name and role, task, place, units done, tools, credits and the last things it said.
 */
import type { Layout } from "@tilo/contracts";
import { act } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { villageBasicLayout } from "../../../test-support/worldFixtures";
import { ev, fakeWorld, resetEvents, withClient } from "../../../test-support/worldLive";
import { resetSpotlights, setHover } from "../../world/spotlight";
import { AgentLayer } from "./AgentLayer";

afterEach(() => {
  cleanup();
  resetSpotlights();
});

const layout = villageBasicLayout() as unknown as Layout;
const run = () => {
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
    ev("agent.working", "A_s1", "B2", { unit: "U1" }, {
      credits: 2,
      trace: { tool: "gmail.search" },
    } as never),
    ev("agent.handoff", "A_s1", "A_l1", { envelope: { summary: "Triaged 12 emails." } }),
  ];
};

async function show(hover: string | null) {
  const world = fakeWorld(layout, run());
  const m = mount(withClient(world.client, <AgentLayer worldId="w_live" rooms={null} />));
  await act(async () => {
    await Promise.resolve();
  });
  act(() => setHover("w_live", hover, hover ? { x: 120, y: 80 } : null));
  return m;
}

describe("TILO-T-WORLD agent hover card", () => {
  it("shows nothing while no agent is hovered", async () => {
    const m = await show(null);
    expect(m.container.querySelector('[data-testid="agent-card"]')).toBeNull();
  });

  it("lights the hovered agent's stats card with its recorded facts", async () => {
    const m = await show("A_s1");
    const card = m.container.querySelector('[data-testid="agent-card"]');
    expect(card).not.toBeNull();
    const text = card?.textContent ?? "";
    expect(text).toContain("Specialist 1");
    expect(text).toContain("Triage the inbox");
    expect(text).toContain("Reply Desk");
    expect(text).toContain("gmail.search");
    expect(text).toContain("Triaged 12 emails.");
    expect(card?.querySelector(".tw-facts__grid")?.textContent).toContain("2");
  });

  it("an agent with nothing recorded says so and invents no numbers", async () => {
    const m = await show("A_s2");
    const text = m.container.querySelector('[data-testid="agent-card"]')?.textContent ?? "";
    expect(text).toContain("none recorded");
    expect(text).toContain("Nothing said yet.");
  });
});
