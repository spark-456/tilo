// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { liveWorldsApi, mountWorld } from "../../../../test-support/park/worldHarness";
import { EVENTS_VILLAGE_BASIC } from "../../../api/fixtures/events";
import { HttpClient } from "../../../api/http";
import type { World } from "../../api/types";

afterEach(cleanup);

async function replay(seq: number, withoutEntities = false) {
  const api = liveWorldsApi();
  const readWorlds = api.getWorlds;
  api.getWorlds = vi.fn(async (...args: Parameters<typeof readWorlds>) => {
    const result = await readWorlds(...args);
    return {
      ...result,
      data: result.data.map((world: World) => ({
        ...world,
        tier: "City" as const,
        plan: undefined,
      })),
    };
  });
  api.getPlans = vi.fn(async () => ({ data: {}, source: "live" as const }));
  const rows = EVENTS_VILLAGE_BASIC.filter(
    (event) =>
      event.seq <= seq && (!withoutEntities || !/^(district|building|agent)\./.test(event.type)),
  ).map((event) => ({
    ...event,
    world_id: "hires",
  }));
  const fetch = vi.fn(async (url: string | URL | Request) =>
    String(url).includes("/events")
      ? new Response(JSON.stringify({ events: rows }))
      : new Response("{}", { status: 404 }),
  );
  const client = new HttpClient({ baseUrl: "https://api.test", fetch, pollMs: 60_000 });
  const rig = await mountWorld({ id: "hires", api, client });
  return { ...rig, fetch, rows };
}

it("LIVE-WORLD-BUILD GET events draws recorded districts, buildings and agents without a Park plan", async () => {
  const rig = await replay(EVENTS_VILLAGE_BASIC.at(-1)?.seq ?? 0);
  expect(rig.fetch.mock.calls.some(([url]) => String(url).includes("/worlds/hires/events"))).toBe(
    true,
  );
  const map = rig.el.querySelector("[data-recorded-world]");
  expect(map).not.toBeNull();
  const districts = rig.rows.filter((event) => event.type === "district.created");
  const agents = rig.rows.filter((event) => event.type === "agent.spawned");
  const buildings = rig.rows.filter((event) => event.type === "building.planned");
  expect(map?.querySelectorAll("[data-recorded-district]")).toHaveLength(districts.length);
  expect(map?.querySelectorAll("[data-recorded-agent]")).toHaveLength(agents.length);
  expect(map?.querySelectorAll("[data-recorded-building]")).toHaveLength(buildings.length);
  for (const event of [...districts, ...agents, ...buildings]) {
    expect(map?.innerHTML).toContain(event.target);
  }
  expect(map?.querySelector("svg")).not.toBeNull();
  expect(map?.querySelector("animate, animateTransform")).toBeNull();
  expect(rig.el.textContent).toContain("Mail");
});

it("LIVE-WORLD-BUILD a started run with no entity event draws no invented map", async () => {
  const started = EVENTS_VILLAGE_BASIC.find((event) => event.type === "world.started");
  expect(started).toBeDefined();
  const rig = await replay(started?.seq ?? 0, true);
  expect(rig.el.querySelector("[data-recorded-world]")).toBeNull();
  expect(rig.el.textContent).toContain("Waiting for recorded districts and agents");
});

it("LIVE-WORLD-BUILD partial replay draws no agents before their spawn events", async () => {
  const firstAgent = EVENTS_VILLAGE_BASIC.find((event) => event.type === "agent.spawned");
  const rig = await replay((firstAgent?.seq ?? 1) - 1);
  expect(rig.el.querySelectorAll("[data-recorded-district]").length).toBeGreaterThan(0);
  expect(rig.el.querySelectorAll("[data-recorded-agent]")).toHaveLength(0);
  expect(rig.el.querySelectorAll("[data-recorded-building]").length).toBeGreaterThan(0);
});
