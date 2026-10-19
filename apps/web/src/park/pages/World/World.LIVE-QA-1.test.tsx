// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { liveWorldsApi, mountWorld, textOf } from "../../../../test-support/park/worldHarness";
import { EVENTS_VILLAGE_BASIC } from "../../../api/fixtures/events";
import { HttpClient } from "../../../api/http";
import type { World } from "../../api/types";

afterEach(cleanup);

async function liveTier(tier: World["tier"], withEvents: boolean) {
  const api = liveWorldsApi();
  const readWorlds = api.getWorlds;
  api.getWorlds = vi.fn(async (...args: Parameters<typeof readWorlds>) => {
    const result = await readWorlds(...args);
    return { ...result, data: result.data.map((world: World) => ({ ...world, tier })) };
  });
  const client = new HttpClient({
    baseUrl: "http://localhost:0",
    fetch: async () => new Response("{}", { status: 404 }),
  });
  client.subscribeEvents = (world, onEvent) => {
    if (withEvents) {
      for (const event of EVENTS_VILLAGE_BASIC) onEvent({ ...event, world_id: world });
    }
    return () => undefined;
  };
  return mountWorld({ id: "hires", api, client });
}

for (const tier of ["Village", "Town", "City"] as const) {
  it(`QA-1 live ${tier} exposes all lenses and the recorded event view`, async () => {
    const rig = await liveTier(tier, true);
    expect(rig.el.querySelector("a.park-world-live")?.getAttribute("href")).toBe(
      "/world/hires/stage",
    );
    const lenses = rig.el.querySelector('nav[aria-label="Run views"]');
    expect(lenses).not.toBeNull();
    const links = Array.from(lenses?.querySelectorAll("a") ?? []);
    expect(links.map(textOf)).toEqual(["Story", "Trace", "Delivery", "Inspect"]);
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/world/hires/story",
      "/world/hires/trace",
      "/world/hires/delivery",
      "/world/hires/inspect/B1",
    ]);
    const progress = rig.el.querySelector('section[aria-label="Live run"]');
    expect(progress).not.toBeNull();
    expect(progress?.textContent).toContain(`${EVENTS_VILLAGE_BASIC.length} recorded events`);
  });

  it(`QA-1 live ${tier} with no events explains every disabled lens`, async () => {
    const rig = await liveTier(tier, false);
    const links = Array.from(
      rig.el.querySelectorAll('a.park-world-live, nav[aria-label="Run views"] a'),
    );
    expect(links).toHaveLength(5);
    for (const link of links) {
      expect(link.hasAttribute("href")).toBe(false);
      expect(link.getAttribute("aria-disabled")).toBe("true");
      const reason = link.getAttribute("aria-describedby");
      expect(reason).toBeTruthy();
      expect(rig.el.querySelector(`[id="${reason}"]`)?.textContent).toContain(
        "recorded no events yet",
      );
    }
  });
}
