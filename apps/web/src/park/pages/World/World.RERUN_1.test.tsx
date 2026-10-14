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
  ev(1, "budget.granted", { cap: 80, granted: 80 }),
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
    expect(pageText(rig.el)).toContain("spending cap of 80 credits");
    expect(pageText(rig.el)).toContain("in addition to any credits already used");
    expect(pageText(rig.el)).toContain("No outbound sends are recorded");

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

  it("discloses recorded sends and the latest approved cap before starting", async () => {
    const start = vi.fn(async () => ({ world_id: "w_new", task_id: "t_new" }));
    const events = [
      ev(1, "budget.granted", { cap: 80 }),
      ev(2, "budget.granted", { cap: 125.5 }),
      ev(3, "data.transfer", { direction: "in", outbox_id: null }),
      ev(4, "data.transfer", { direction: "out", outbox_id: "o_first" }),
      ev(5, "artifact.delivered", { outbox_id: "o_first" }),
      ev(6, "artifact.delivered", { outbox_id: "o_other" }),
      ev(7, "artifact.delivered", { outbox_id: null }),
      ev(8, "world.failed", { reason: RESTART }),
    ];
    const rig = await mountWorld({
      id: "hires",
      api: liveWorldsApi(),
      client: clientWith(events, start),
    });
    expect(pageText(rig.el)).toContain("spending cap of 125.5 credits");
    expect(pageText(rig.el)).toContain(
      "already sent things outside Tilo (2 recorded outbound actions)",
    );
    expect(pageText(rig.el)).toContain("Starting again may send them again");
    expect(start).not.toHaveBeenCalled();
    click(control(rig.el, "Start it again"));
    await settle();
    expect(start).toHaveBeenCalledTimes(1);
  });

  it.each([undefined, {}, { cap: -1 }, { cap: "80" }])(
    "cannot approve an unavailable cap: %s",
    async (grant) => {
      const start = vi.fn(async () => ({ world_id: "w_new", task_id: "t_new" }));
      const events = [ev(1, "budget.granted", grant), ...STOPPED.slice(1)];
      const rig = await mountWorld({
        id: "hires",
        api: liveWorldsApi(),
        client: clientWith(events, start),
      });
      expect(pageText(rig.el)).toContain("spending cap is not available");
      expect((control(rig.el, "Start it again") as HTMLButtonElement).disabled).toBe(true);
      click(control(rig.el, "Start it again"));
      await settle();
      expect(start).not.toHaveBeenCalled();
    },
  );

  it("RERUN_1_another_stop_shows_its_own_recorded_reason_and_a_running_or_finished_world_offers_nothing", async () => {
    // WORLD-USEFUL: any stop shows the reason the run recorded; "Tilo restarted" is said only of a restart stop.
    const other = [
      ev(1, "world.started"),
      ev(2, "world.failed", { reason: "an internal error stopped the work", unit: null }),
    ];
    const stopped = await mountWorld({
      id: "hires",
      api: liveWorldsApi(),
      client: clientWith(other),
    });
    expect(pageText(stopped.el)).toContain("Why: an internal error stopped the work");
    expect(pageText(stopped.el)).not.toContain("Tilo restarted while this was running");
    expect(hasControl(stopped.el, "Start it again")).toBe(true);
    cleanup();
    for (const events of [[ev(1, "world.started")], [...STOPPED, ev(4, "world.completed", {})]]) {
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
