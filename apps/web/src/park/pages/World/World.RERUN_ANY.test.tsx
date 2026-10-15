// @vitest-environment happy-dom
// RERUN-ANY: a world that stopped for any recorded reason (here the live "a unit failed, so the work stopped") offers
// "Start it again", which calls `/rerun` and opens the new world; "New task" appears only when the server refuses (409).
// No network is touched.
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

const ev = (seq: number, type: string, data?: unknown): RunEvent => ({
  seq,
  type,
  ts: `2026-10-15T09:0${seq}:00.000Z`,
  credits: 0,
  summary: type,
  ...(data === undefined ? {} : { data }),
});

const UNIT_FAILED = [
  ev(1, "budget.granted", { cap: 40, granted: 40 }),
  ev(2, "world.started"),
  ev(3, "world.failed", { reason: "a unit failed, so the work stopped", unit: "U1" }),
];

function clientWith(startAgain: HttpClient["startAgain"]): HttpClient {
  const client = new HttpClient({
    baseUrl: "http://localhost:0",
    fetch: async () => new Response("{}", { status: 404 }),
  });
  client.subscribeEvents = (_world, onEvent) => {
    for (const e of UNIT_FAILED) onEvent(e as unknown as Parameters<typeof onEvent>[0]);
    return () => undefined;
  };
  client.startAgain = startAgain;
  return client;
}

describe("RERUN_ANY Start it again for any stopped run", () => {
  it("RERUN_ANY_a_unit_failure_calls_rerun_and_opens_the_new_world", async () => {
    const start = vi.fn(async () => ({ world_id: "w_new", task_id: "t_new" }));
    const rig = await mountWorld({ id: "hires", api: liveWorldsApi(), client: clientWith(start) });
    expect(pageText(rig.el)).not.toContain("Tilo restarted while this was running");

    click(control(rig.el, "Start it again"));
    await settle();

    expect(start).toHaveBeenCalledWith("hires");
    expect(rig.app.go).toHaveBeenCalledWith("world", { id: "w_new" });
    expect(hasControl(rig.el, "New task")).toBe(false);
  });

  it("RERUN_ANY_only_a_server_409_falls_back_to_new_task", async () => {
    const start = vi.fn(async () => {
      throw Object.assign(new Error("409"), { status: 409 });
    });
    const rig = await mountWorld({ id: "hires", api: liveWorldsApi(), client: clientWith(start) });

    click(control(rig.el, "Start it again"));
    await settle();

    expect(start).toHaveBeenCalledTimes(1);
    expect(pageText(rig.el)).toContain("cannot start this run again from here");
    click(control(rig.el, "New task"));
    expect(rig.app.go).toHaveBeenCalledWith("home");
  });
});
