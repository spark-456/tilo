// @vitest-environment happy-dom
// WORLD-USEFUL: a real run's World page is something a person can read and use. Replays one run's recorded events
// stage by stage (no network, no paid call) and checks what the page says at each: the plan forming, agents at
// work with a plain progress line, what was assumed instead of asked (chips), the finished deliverable readable on
// the page with Open and Download, and a failure that shows the recorded reason with "Start it again".
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import {
  control,
  hasControl,
  liveWorldsApi,
  mountWorld,
  pageText,
  settle,
  textOf,
} from "../../../../test-support/park/worldHarness";
import { EVENTS_VILLAGE_BASIC } from "../../../api/fixtures/events";
import { HttpClient } from "../../../api/http";
import { installResultReader } from "../../api/results";
import { Markdown } from "./markdown";
import { runView } from "./runView";
import type { RunEvent } from "./useRunEvents";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

let seq = 0;
const ev = (type: string, summary: string, data: unknown = {}, credits = 0): RunEvent => ({
  seq: ++seq,
  type,
  ts: `2026-10-15T09:${String(seq).padStart(2, "0")}:00.000Z`,
  credits,
  summary,
  data,
});
const fresh = () => {
  seq = 0;
};

const PLAN = [
  () => ev("world.requested", "You asked Tilo to plan the trip.", { title: "Plan a road trip" }),
  () => ev("budget.granted", "You approved a budget of 40 credits.", { granted: 40, cap: 40 }),
  () =>
    ev("world.planned", "The Director planned 3 units.", {
      tier: "village",
      approach: "quick",
      unit_count: 3,
      credits: { min: 5, max: 20 },
    }),
];
const START = () =>
  ev("world.started", "Work started with a budget of 40 credits.", { budget_cap: 40 });
const WORKING = (unit: string, text: string) => () => ev("agent.working", text, { unit });
const NOTES =
  "# Road trip\n\n- **Day 1**: drive to Bangalore\n- Day 2: on to Gokarna\n\n| Leg | Hours |\n| --- | --- |\n| A to B | 6 |\n";

/** A client whose run records what the test emits, when it emits it. */
function liveFeed() {
  const client = new HttpClient({
    baseUrl: "http://localhost:0",
    fetch: async () => new Response("{}", { status: 404 }),
  });
  let push: ((e: never) => void) | null = null;
  client.subscribeEvents = (_world, onEvent) => {
    push = onEvent as unknown as (e: never) => void;
    return () => undefined;
  };
  const emit = async (...events: RunEvent[]) => {
    await act(async () => {
      for (const e of events) push?.(e as never);
    });
    await settle();
  };
  return { client, emit };
}

function api(
  result: () => Promise<Blob> = async () => new Blob([NOTES], { type: "text/markdown" }),
) {
  const a = liveWorldsApi();
  installResultReader(a, result);
  return a;
}

describe("WORLD_USEFUL runView: the progress line comes from recorded events only", () => {
  it("says nothing was recorded when nothing was", () => {
    fresh();
    expect(runView([]).line).toBe("Getting ready. Nothing has been recorded yet.");
  });

  it("names the step and what the agents are doing now, and never counts a step no event gave out", () => {
    fresh();
    const planned = PLAN.map((f) => f());
    expect(runView([...planned]).line).toBe("The plan is ready: 3 steps. Waiting to start.");
    const working = [...planned, START()];
    expect(runView(working).line).toBe("Working.");
    const one = [...working, WORKING("U1", "The Specialist is mapping the route")()];
    expect(runView(one)).toMatchObject({
      phase: "working",
      begun: 1,
      total: 3,
      percent: 33,
      line: "Step 1 of 3: The Specialist is mapping the route.",
    });
    const two = [
      ...one,
      ev("agent.assigned", "The Lead gave the stays to a Specialist.", { unit: "U2" }),
    ];
    expect(runView(two).line).toBe("Step 2 of 3: The Lead gave the stays to a Specialist.");
  });

  it("reads assumptions from 'Assumed:' events, once each", () => {
    fresh();
    const events = [
      ev("agent.working", "Assumed: you travel by car", { unit: null }),
      ev("agent.working", "Assumed: you travel by car", { unit: null }),
      ev("agent.working", "Assumed:  a budget of INR 40000", { unit: null }),
      ev("agent.working", "The Specialist is checking the Assumed: weather.", { unit: null }),
    ];
    expect(runView(events).assumptions).toEqual(["you travel by car", "a budget of INR 40000"]);
  });

  it("a stop carries its recorded reason; a plain finish with a deliverable can be read", () => {
    fresh();
    const failed = [
      START(),
      ev("world.failed", "Stopped.", { reason: "the route tool is not connected", unit: "U2" }),
    ];
    expect(runView(failed)).toMatchObject({
      phase: "failed",
      failure: { reason: "the route tool is not connected", unit: "U2" },
      line: "Stopped: the route tool is not connected.",
      deliverable: false,
    });
    const done = [
      ...PLAN.map((f) => f()),
      START(),
      ev("artifact.delivered", "The plan is ready in Tilo.", {
        artifact: {},
        format: "in_app",
        outbox_id: null,
      }),
      ev("world.completed", "Done.", { credits_used: 4, deliverable_count: 1 }),
    ];
    expect(runView(done)).toMatchObject({ phase: "done", percent: 100, deliverable: true });
    expect(runView(done).line).toBe("Done. All 3 steps finished, 1 deliverable ready below.");
  });
});

describe("WORLD_USEFUL markdown: a result reads as a document and can never inject markup", () => {
  it("draws headings, lists, tables and bold; keeps raw html and script links as text", () => {
    const m = mount(
      <Markdown
        text={`${NOTES}\n<script>alert(1)</script>\n\n[bad](javascript:alert(1)) and [ok](https://example.com/x)`}
      />,
    );
    const root = m.container;
    expect(root.querySelector("h3")?.textContent).toBe("Road trip");
    expect(root.querySelectorAll("li")).toHaveLength(2);
    expect(root.querySelector("strong")?.textContent).toBe("Day 1");
    expect(root.querySelectorAll("th")).toHaveLength(2);
    expect(root.querySelectorAll("td")).toHaveLength(2);
    expect(root.querySelector("script")).toBeNull();
    const links = [...root.querySelectorAll("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://example.com/x"]);
    expect(root.textContent).toContain("<script>alert(1)</script>");
  });
});

describe("WORLD_USEFUL the World page of a live run", () => {
  it("WORLD_USEFUL_journey_plan_forming_agents_working_assumption_result", async () => {
    fresh();
    const { client, emit } = liveFeed();
    const rig = await mountWorld({ id: "hires", api: api(), client });
    const status = () => textOf(rig.el.querySelector('[data-testid="run-status"]') as Element);

    // nothing recorded yet: it says so, there is no result and no invented step
    expect(pageText(rig.el)).toContain("No recorded events yet");
    expect(rig.el.querySelector('[data-testid="run-result"]')).toBeNull();

    // 1. the plan is forming
    await emit(ev("world.requested", "You asked Tilo to plan the trip.", { title: "t" }));
    expect(status()).toContain("Planning.");
    await emit(...PLAN.slice(1).map((f) => f()));
    expect(status()).toContain("The plan is ready: 3 steps. Waiting to start.");

    // 2. agents at work: step n of m and what they are doing now, from the latest event
    await emit(START(), ev("agent.spawned", "A Specialist joined.", { role: "specialist" }));
    await emit(WORKING("U1", "The Specialist is mapping the route")());
    expect(status()).toContain("Step 1 of 3: The Specialist is mapping the route.");
    const bar = rig.el.querySelector("progress.park-world-progress") as HTMLProgressElement;
    expect(bar.value).toBe(33);
    expect(rig.el.querySelector(".park-world-chip")?.textContent).toContain("Running");
    expect(rig.el.querySelector('[data-testid="run-result"]')).toBeNull();

    // 3. a recorded assumption shows as a chip
    await emit(ev("agent.working", "Assumed: you travel by road in your own car", { unit: "U1" }));
    const chips = [...rig.el.querySelectorAll(".park-world-assumedchip")].map((c) => textOf(c));
    expect(chips).toEqual(["Assumed: you travel by road in your own car"]);

    // 4. the work finishes: the deliverable is readable here, with Open and Download
    await emit(
      WORKING("U2", "The Specialist is booking the stays")(),
      WORKING("U3", "The Specialist is writing the plan")(),
      ev("artifact.created", "The plan was written.", {
        artifact: { artifact_id: "art_plan", version: 1 },
      }),
      ev("artifact.delivered", "The plan is ready in Tilo.", {
        artifact: { artifact_id: "art_plan", version: 1 },
        format: "in_app",
        outbox_id: null,
      }),
      ev("world.completed", "Done.", { credits_used: 4, deliverable_count: 1 }),
    );
    expect(status()).toContain("Done. All 3 steps finished, 1 deliverable ready below.");
    expect(rig.el.querySelector(".park-world-chip")?.textContent).toContain("Ready");
    const text = rig.el.querySelector('[data-testid="result-text"]') as HTMLElement;
    expect(text.querySelector("h3")?.textContent).toBe("Road trip");
    expect(textOf(text)).toContain("drive to Bangalore");
    expect(text.querySelectorAll("table")).toHaveLength(1);
    expect(hasControl(rig.el, "Pause")).toBe(false);
    for (const label of ["Open result", "Download"]) {
      const b = control(rig.el, label) as HTMLButtonElement;
      expect(b.disabled).toBe(false);
      expect(b.getAttribute("aria-disabled")).not.toBe("true");
    }
    // the assumption stays on the page after the finish
    expect(rig.el.querySelectorAll(".park-world-assumedchip")).toHaveLength(1);
  });

  it("WORLD_USEFUL_download_saves_the_result_and_open_shows_it_in_a_new_tab", async () => {
    fresh();
    const { client, emit } = liveFeed();
    const rig = await mountWorld({ id: "hires", api: api(), client });
    await emit(
      ...PLAN.map((f) => f()),
      START(),
      ev("artifact.delivered", "Ready.", { artifact: {}, format: "in_app", outbox_id: null }),
      ev("world.completed", "Done.", { credits_used: 1, deliverable_count: 1 }),
    );
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:result");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const clicks: HTMLAnchorElement[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicks.push(this);
    });
    click(control(rig.el, "Download"));
    expect(clicks).toHaveLength(1);
    expect(clicks[0]?.download).toBe("tilo-result-hires.md");
    expect(revoke).toHaveBeenCalledWith("blob:result");
    click(control(rig.el, "Open result"));
    expect(clicks).toHaveLength(2);
    expect(clicks[1]?.target).toBe("_blank");
    expect(clicks[1]?.rel).toContain("noopener");
    expect(create).toHaveBeenCalledTimes(2);
  });

  it("WORLD_USEFUL_a_result_that_cannot_be_read_says_so_and_can_be_tried_again", async () => {
    fresh();
    const read = vi
      .fn<() => Promise<Blob>>()
      .mockRejectedValueOnce(new Error("503"))
      .mockResolvedValue(new Blob(["Plain notes"], { type: "text/plain" }));
    const { client, emit } = liveFeed();
    const rig = await mountWorld({ id: "hires", api: api(read), client });
    await emit(
      ...PLAN.map((f) => f()),
      START(),
      ev("artifact.delivered", "Ready.", { artifact: {}, format: "in_app", outbox_id: null }),
      ev("world.completed", "Done.", { credits_used: 1, deliverable_count: 1 }),
    );
    expect(pageText(rig.el)).toContain("The result could not be loaded");
    click(control(rig.el, "Try again"));
    await settle();
    expect(textOf(rig.el.querySelector('[data-testid="result-text"]') as Element)).toBe(
      "Plain notes",
    );
  });

  it("WORLD_USEFUL_a_finished_run_that_delivered_nothing_offers_no_result", async () => {
    fresh();
    const { client, emit } = liveFeed();
    const rig = await mountWorld({ id: "hires", api: api(), client });
    await emit(
      ...PLAN.map((f) => f()),
      START(),
      ev("world.completed", "Done.", { credits_used: 1, deliverable_count: 0 }),
    );
    expect(pageText(rig.el)).toContain("nothing was delivered");
    expect(rig.el.querySelector('[data-testid="run-result"]')).toBeNull();
    expect(hasControl(rig.el, "Open result")).toBe(false);
  });

  it("WORLD_USEFUL_a_failure_shows_the_recorded_reason_and_start_it_again_never_ready", async () => {
    fresh();
    const start = vi.fn(async () => ({ world_id: "w_new", task_id: "t_new" }));
    const { client, emit } = liveFeed();
    client.startAgain = start;
    const rig = await mountWorld({ id: "hires", api: api(), client });
    await emit(
      ...PLAN.map((f) => f()),
      START(),
      WORKING("U1", "The Specialist is mapping the route")(),
      ev("world.failed", "Stopped: the route tool is not connected", {
        reason: "the route tool is not connected",
        unit: "U1",
      }),
    );
    const failed = rig.el.querySelector('[data-testid="run-failed"]') as HTMLElement;
    expect(textOf(failed)).toContain("Why: the route tool is not connected");
    expect(pageText(rig.el)).toContain("Stopped at step 1 of 3: the route tool is not connected.");
    expect(rig.el.querySelector(".park-world-chip")?.textContent).toContain("Stopped");
    expect(rig.el.querySelector(".park-world-chip")?.textContent).not.toContain("Ready");
    expect(rig.el.querySelector('[data-testid="run-result"]')).toBeNull();
    expect(hasControl(rig.el, "Open result")).toBe(false);
    expect(pageText(rig.el)).not.toContain("a unit failed");
    expect(rig.el.querySelector(".park-world-runstatus progress")).toBeNull();

    click(control(rig.el, "Start it again"));
    await settle();
    expect(start).toHaveBeenCalledWith("hires");
    expect(rig.app.go).toHaveBeenCalledWith("world", { id: "w_new" });
  });

  it("WORLD_USEFUL_a_stop_the_server_will_not_restart_points_to_a_new_task", async () => {
    fresh();
    const refused = Object.assign(new Error("409"), { status: 409 });
    const { client, emit } = liveFeed();
    client.startAgain = vi.fn(async () => {
      throw refused;
    });
    const rig = await mountWorld({ id: "hires", api: api(), client });
    await emit(
      START(),
      ev("budget.granted", "Approved.", { cap: 20, granted: 20 }),
      ev("world.failed", "Stopped.", { reason: "a tool was off", unit: null }),
    );
    click(control(rig.el, "Start it again"));
    await settle();
    expect(pageText(rig.el)).toContain("cannot start this run again from here");
    click(control(rig.el, "New task"));
    expect(rig.app.go).toHaveBeenCalledWith("home");
  });

  it("WORLD_USEFUL_the_recorded_village_run_ends_with_its_result_readable", async () => {
    // The recorded fixture stream (contracts/fixtures/streams/village-basic.jsonl) replayed in order, as the API serves it.
    const { client, emit } = liveFeed();
    const rig = await mountWorld({ id: "hires", api: api(), client });
    const status = () => textOf(rig.el.querySelector('[data-testid="run-status"]') as Element);
    const at = (n: number) =>
      EVENTS_VILLAGE_BASIC.filter((e) => e.seq <= n) as unknown as RunEvent[];
    await emit(...at(4));
    expect(status()).toContain("The plan is ready: 2 steps");
    await emit(
      ...(EVENTS_VILLAGE_BASIC.filter((e) => e.seq > 4 && e.seq <= 24) as unknown as RunEvent[]),
    );
    expect(status()).toContain("Step 1 of 2: The Specialist is sorting 12 emails.");
    await emit(
      ...(EVENTS_VILLAGE_BASIC.filter((e) => e.seq > 24 && e.seq <= 34) as unknown as RunEvent[]),
    );
    expect(status()).toContain("Waiting for you: 1 decision.");
    await emit(...(EVENTS_VILLAGE_BASIC.filter((e) => e.seq > 34) as unknown as RunEvent[]));
    expect(status()).toContain("Done. All 2 steps finished, 1 deliverable ready below.");
    expect(rig.el.querySelector('[data-testid="result-text"]')).not.toBeNull();
  });
});
