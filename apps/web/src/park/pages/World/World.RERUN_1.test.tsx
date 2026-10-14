// @vitest-environment happy-dom
// RERUN-1: a world a restart stopped (world.failed "Tilo restarted during this run; start it again") offers ONE
// honest action on its World page, "Start it again", which asks the API for a new run of the same task and opens the
// new world. No other stop, and no unfinished run, offers it. No network is touched.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click } from "../../../../test-support/park/componentsHarness";
import {
  control,
  hasControl,
  liveWorldsApi,
  mountWorld,
  pageText,
  settle,
} from "../../../../test-support/park/worldHarness";
import { HttpClient } from "../../../api/http";
import type { RunEvent } from "./useRunEvents";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const RESTART = "Tilo restarted during this run; start it again";
const ev = (seq: number, type: string, data?: unknown): RunEvent => ({
  seq,
  type,
  ts: `2026-10-14T11:5${seq}:00.000Z`,
  credits: 0,
  summary: type,
  ...(data === undefined ? {} : { data }),
});

function clientWith(events: RunEvent[], startAgain?: HttpClient["startAgain"]): HttpClient {
  const client = new HttpClient({
    baseUrl: "http://localhost:0",
    fetch: async () => new Response("{}", { status: 404 }),
  });
  client.subscribeEvents = (_world, onEvent) => {
    for (const e of events) onEvent(e as unknown as Parameters<typeof onEvent>[0]);
    return () => undefined;
  };
  if (startAgain) client.startAgain = startAgain;
  return client;
}

const STOPPED = [
  ev(1, "world.requested"),
  ev(2, "world.started"),
  ev(3, "world.failed", { reason: RESTART, unit: null }),
];

describe("RERUN_1 Start it again", () => {
  it("RERUN_1_a_restart_stop_offers_one_action_that_starts_a_new_run_and_opens_it", async () => {
    const start = vi.fn(async () => ({ world_id: "w_new", task_id: "t_new" }));
    const rig = await mountWorld({
      id: "hires",
      api: liveWorldsApi(),
      client: clientWith(STOPPED, start),
    });
    expect(pageText(rig.el)).toContain("Tilo restarted while this was running");

    click(control(rig.el, "Start it again"));
    await settle();

    expect(start).toHaveBeenCalledTimes(1);
    expect(start).toHaveBeenCalledWith("hires");
    expect(rig.app.go).toHaveBeenCalledWith("world", { id: "w_new" });
  });

  it("RERUN_1_a_refused_start_says_so_in_words_and_keeps_the_button", async () => {
    const start = vi.fn(async () => {
      throw new Error("503");
    });
    const rig = await mountWorld({
      id: "hires",
      api: liveWorldsApi(),
      client: clientWith(STOPPED, start),
    });

    click(control(rig.el, "Start it again"));
    await settle();

    expect(pageText(rig.el)).toContain("Nothing was started and nothing was charged");
    expect(hasControl(rig.el, "Start it again")).toBe(true);
    expect(rig.app.go).not.toHaveBeenCalled();
  });

  it("RERUN_1_other_stops_and_running_worlds_offer_nothing", async () => {
    const other = [
      ev(1, "world.started"),
      ev(2, "world.failed", { reason: "an internal error stopped the work", unit: null }),
    ];
    for (const events of [
      other,
      [ev(1, "world.started")],
      [...STOPPED, ev(4, "world.completed", {})],
    ]) {
      const rig = await mountWorld({
        id: "hires",
        api: liveWorldsApi(),
        client: clientWith(events),
      });
      expect(hasControl(rig.el, "Start it again")).toBe(false);
      cleanup();
    }
  });
});
