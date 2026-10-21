// @vitest-environment happy-dom
// UX-SMOOTH (owner, 21 Oct: "stuck on the loading screen ... by the time we load in, everything is already complete"):
// the World page of a world opened the moment Start answered never says "World not found" while the list read has
// not caught up: it says it is opening and reads the list again until the world is there. A live run with no recorded
// plan shows no invented step or credit totals.
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { fakeScheduler } from "../../../../test-support/park/appHarness";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { appFor } from "../../../../test-support/park/worldHarness";
import { HttpClient } from "../../../api/http";
import { createFixtureApi } from "../../api/fixtureApi";
import type { World } from "../../api/types";
import { markPendingWorld } from "../../app/PendingWorldRoute";
import { ParkProvider } from "../../app/context";
import { WorldPage } from "./WorldPage";

afterEach(cleanup);

it("UX_SMOOTH_a_just_started_world_opens_and_is_read_again_until_the_list_carries_it", async () => {
  const api = createFixtureApi();
  const first = (await api.getWorlds({}, [])).data[0] as World;
  let listed: World[] = [];
  const reads = vi.fn(async () => ({ data: listed, source: "live" as const }));
  api.getWorlds = reads;
  const fetch = vi.fn(async () => new Response(JSON.stringify({ events: [] }), { status: 200 }));
  const client = new HttpClient({ baseUrl: "https://api.test", fetch });
  const sch = fakeScheduler();
  markPendingWorld("w_new", "Plan the launch");
  let el: HTMLElement | undefined;
  await act(async () => {
    el = mount(
      <ParkProvider api={api} worldClient={client} schedule={sch.schedule}>
        <WorldPage app={appFor("w_new")} />
      </ParkProvider>,
    ).container;
  });
  expect(el?.textContent).toContain("Opening your new world");
  expect(el?.textContent).not.toContain("World not found");
  // The server now lists it: the next scheduled read finds it and the page shows the world.
  listed = [{ ...first, id: "w_new", name: "Plan the launch", sample: false }];
  const timer = sch.live().find((t) => t.ms === 1500);
  expect(timer, "a re-read is scheduled").toBeDefined();
  await act(async () => {
    sch.fire(timer);
    await Promise.resolve();
  });
  await act(async () => Promise.resolve());
  expect(reads.mock.calls.length).toBeGreaterThan(1);
  expect(el?.querySelector("h1.park-world-h1")?.textContent).toBe("Plan the launch");
  // No plan is recorded yet: no invented "of 7" steps or "of 120" credits.
  const head = el?.querySelector(".park-world-head")?.textContent ?? "";
  expect(head).not.toMatch(/of 7|of 120/);
});
