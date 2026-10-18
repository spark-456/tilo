// @vitest-environment happy-dom
import type { Layout } from "@tilo/contracts";
import { act } from "react";
import { afterEach, expect, test } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { villageBasicLayout } from "../../../test-support/worldFixtures";
import { ev, fakeWorld, resetEvents, withClient } from "../../../test-support/worldLive";
import { registerProbe, resetSpotlights } from "../../world/spotlight";
import { AgentLayer } from "./AgentLayer";

afterEach(() => {
  cleanup();
  resetSpotlights();
});

test("R-WORLD-SPREAD talking dots sit halfway between the two recorded agents", async () => {
  resetEvents();
  const events = [
    ev("agent.spawned", "system", "A_l1", { role: "lead" }),
    ev("agent.moved", "A_l1", "B1", { from: "B1" }),
    ev("agent.spawned", "A_l1", "A_s1", { role: "specialist" }),
    ev("agent.moved", "A_s1", "B2", { from: "B1" }),
    ev("agent.handoff", "A_s1", "A_l1", { envelope: { summary: "Ready" } }),
  ];
  const layout = villageBasicLayout() as unknown as Layout;
  const world = fakeWorld(layout, events);
  registerProbe("w_live", {
    agentAt: () => null,
    locate: (id) =>
      id === "A_s1" ? { x: 100, y: 180 } : id === "A_l1" ? { x: 260, y: 140 } : null,
    isWalking: () => false,
  });
  const mounted = mount(withClient(world.client, <AgentLayer worldId="w_live" rooms={null} />));
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  const dots = mounted.container.querySelector<HTMLElement>('[data-testid="world-talk-dots"]');
  expect(dots?.style.left).toBe("180px");
  expect(dots?.style.top).toBe("126px");
});
