// @vitest-environment happy-dom
// UI-10 B8: a real run's World page reads the run's recorded events (GET /worlds/{id}/events through the client's
// subscription). Replays the recorded village-basic stream from the fixtures: no network, no paid call.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import {
  liveWorldsApi,
  mountWorld,
  pageText,
  textOf,
} from "../../../../test-support/park/worldHarness";
import { EVENTS_VILLAGE_BASIC } from "../../../api/fixtures/events";
import { HttpClient } from "../../../api/http";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** An HTTP client whose run has recorded the events up to `seq` (0: none); it never touches the network. */
function runClient(seq: number): HttpClient {
  const client = new HttpClient({
    baseUrl: "http://localhost:0",
    // every other call the page makes answers "nothing here": no network is touched
    fetch: async () => new Response("{}", { status: 404 }),
  });
  client.subscribeEvents = (world, onEvent) => {
    for (const e of EVENTS_VILLAGE_BASIC) if (e.seq <= seq) onEvent({ ...e, world_id: world });
    return () => undefined;
  };
  return client;
}

const live = (seq: number) => ({ api: liveWorldsApi(), client: runClient(seq) });
const LAST = EVENTS_VILLAGE_BASIC.at(-1)?.seq ?? 0;

describe("UI_10_B8 a real run's World page", () => {
  it("UI_10_B8_a_run_with_no_event_says_so_and_its_stage_links_are_off_with_the_reason", async () => {
    const rig = await mountWorld({ id: "hires", ...live(0) });
    expect(pageText(rig.el)).toContain("No recorded events yet");
    const open = rig.el.querySelector("a.park-world-live") as HTMLElement;
    expect(open.hasAttribute("href")).toBe(false);
    expect(open.getAttribute("aria-disabled")).toBe("true");
    expect(textOf(rig.el.querySelector(".park-world-nostage") as Element)).toContain(
      "recorded no events yet",
    );
  });

  it("UI_10_B8_a_run_with_events_shows_its_progress_from_them_and_enables_the_stage", async () => {
    const rig = await mountWorld({ id: "hires", ...live(LAST) });
    const card = rig.el.querySelector('section[aria-label="Live run"]') as HTMLElement;
    expect(card).not.toBeNull();
    const text = textOf(card);
    expect(text).toContain(`${EVENTS_VILLAGE_BASIC.length} recorded events`);
    expect(text).toContain("Done"); // world.completed is the last recorded event
    const spawned = EVENTS_VILLAGE_BASIC.filter((e) => e.type === "agent.spawned").length;
    expect(text).toContain(`Agents${spawned}`);
    const done = EVENTS_VILLAGE_BASIC.filter((e) => e.type === "building.completed").length;
    const planned = EVENTS_VILLAGE_BASIC.filter((e) => e.type === "building.planned").length;
    expect(text).toContain(`Buildings${done} of ${planned} finished`);
    const open = rig.el.querySelector("a.park-world-live") as HTMLElement;
    expect(open.getAttribute("href")).toBe("/world/hires/stage");
  });

  it("UI_10_B8_progress_is_the_events_only_a_partial_run_is_not_done", async () => {
    const midway = EVENTS_VILLAGE_BASIC.find((e) => e.type === "agent.working")?.seq ?? 5;
    const rig = await mountWorld({ id: "hires", ...live(midway) });
    const text = textOf(rig.el.querySelector('section[aria-label="Live run"]') as Element);
    expect(text).toContain("Working");
    expect(text).not.toContain("Done");
  });

  it("UI_10_B8_a_demo_or_fixture_session_gets_no_live_run_card", async () => {
    const demo = await mountWorld({ id: "hires", api: liveWorldsApi(), demo: true }); // a demo has no world client
    expect(demo.el.querySelector('section[aria-label="Live run"]')).toBeNull();
    cleanup();
    const fixture = await mountWorld({ id: "hires" });
    expect(fixture.el.querySelector('section[aria-label="Live run"]')).toBeNull();
  });
});
