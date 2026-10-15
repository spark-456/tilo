// @vitest-environment happy-dom
// STUDIO-3 acceptance, World (design/studio-v2 "Tilo S World.dc.html", "Tilo Studio Canvas" 05 One world): the city
// on the left and the Story / Steps / Result tabs on the right, every word from a recorded event (HR-1..HR-7):
// Story is the run's events in plain words, Steps is the plan in order ("Step n of m"), Result is the delivered
// output with Download and Share. A failed run shows its recorded reason with "Start it again"; one filled button.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readComponentsCss } from "../../../../test-support/park/componentsCss";
import { cleanup, click } from "../../../../test-support/park/componentsHarness";
import {
  control,
  liveWorldsApi,
  mountWorld,
  settle,
  textOf,
} from "../../../../test-support/park/worldHarness";
import { HttpClient } from "../../../api/http";
import { installResultReader } from "../../api/results";
import { runSteps, storyOf } from "./runSteps";
import type { RunEvent } from "./useRunEvents";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

let seq = 0;
const ev = (
  type: string,
  summary: string,
  data: unknown = {},
  extra: Partial<RunEvent> = {},
): RunEvent => ({
  seq: ++seq,
  type,
  ts: `2026-10-15T09:${String(seq).padStart(2, "0")}:00.000Z`,
  credits: 0,
  summary,
  data,
  ...extra,
});

const RUN = (): RunEvent[] => {
  seq = 0;
  return [
    ev("world.requested", "You asked Tilo to plan the trip.", { title: "Plan a road trip" }),
    ev("budget.granted", "You approved a budget of 40 credits.", { granted: 40, cap: 40 }),
    ev("world.planned", "The Director planned 3 units.", {
      tier: "village",
      approach: "quick",
      unit_count: 3,
      credits: { min: 5, max: 20 },
    }),
    ev("world.started", "Work started with a budget of 40 credits.", { budget_cap: 40 }),
    ev("agent.assigned", "The Lead gave the route to a Specialist.", { unit: "U1" }),
    ev(
      "building.constructing",
      "Work is starting at the Map Room.",
      { unit: "U1" },
      { target: "B1" },
    ),
    ev("agent.working", "The Specialist is mapping the coast road.", { unit: "U1" }),
    ev("building.completed", "The Map Room finished the route.", {}, { target: "B1" }),
    ev("agent.assigned", "The Lead gave the stays to a Specialist.", { unit: "U2" }),
    ev("vendor.custom_thing", "An unregistered thing happened.", {}),
  ];
};

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

const api = () => {
  const a = liveWorldsApi();
  installResultReader(
    a,
    async () => new Blob(["# Road trip\n\nDay 1: the coast."], { type: "text/markdown" }),
  );
  return a;
};
const tabs = (el: HTMLElement) => [
  ...el.querySelectorAll<HTMLElement>('[role="tablist"][aria-label="World views"] [role="tab"]'),
];
const tabNamed = (el: HTMLElement, name: string) => {
  const t = tabs(el).find((x) => textOf(x).startsWith(name));
  if (!t) throw new Error(`no ${name} tab`);
  return t;
};
const panel = (el: HTMLElement, name: string) => {
  const id = tabNamed(el, name).getAttribute("aria-controls") ?? "";
  return el.querySelector<HTMLElement>(`#${id}`) as HTMLElement;
};

describe("STUDIO_3 runSteps and storyOf: from the recorded events only", () => {
  it("STUDIO_3_steps_are_the_planned_units_in_order_with_their_own_words", () => {
    const { steps, total, done } = runSteps(RUN());
    expect(total).toBe(3);
    expect(done).toBe(1);
    expect(steps.map((s) => s.state)).toEqual(["done", "started", "planned"]);
    expect(steps[0]?.title).toBe("The Lead gave the route to a Specialist.");
    expect(steps[0]?.detail).toBe("The Map Room finished the route.");
    expect(steps[2]?.title).toBe(""); // a step no event has named has no invented words
  });

  it("STUDIO_3_a_completed_world_finishes_every_step_and_a_failed_one_marks_where_it_stopped", () => {
    const run = RUN();
    expect(
      runSteps([...run, ev("world.completed", "Done.", {})]).steps.every((s) => s.state === "done"),
    ).toBe(true);
    const failed = runSteps([
      ...run,
      ev("world.failed", "Stopped.", { reason: "no tool", unit: "U2" }),
    ]);
    expect(failed.steps[1]?.state).toBe("stopped");
  });

  it("STUDIO_3_story_is_newest_first_and_an_unknown_event_type_stays_out_of_it", () => {
    const story = storyOf(RUN()).map((e) => e.summary);
    expect(story[0]).toBe("The Lead gave the stays to a Specialist.");
    expect(story).not.toContain("An unregistered thing happened.");
    expect(story.at(-1)).toBe("You asked Tilo to plan the trip.");
  });
});

describe("STUDIO_3 the World page of a live run", () => {
  it("STUDIO_3_world_tabs_story_steps_result_from_events", async () => {
    const { client, emit } = liveFeed();
    const rig = await mountWorld({ id: "hires", api: api(), client });
    expect(tabs(rig.el).map((t) => t.getAttribute("aria-selected"))).toEqual([
      "true",
      "false",
      "false",
    ]);
    expect(textOf(panel(rig.el, "Story"))).toContain("Nothing recorded yet");
    await emit(...RUN());

    // Story: the recorded words, newest first; the unknown type is not there
    const story = panel(rig.el, "Story");
    expect(story.hidden).toBe(false);
    expect(textOf(story)).toContain("The Specialist is mapping the coast road.");
    expect(textOf(story)).not.toContain("An unregistered thing happened.");
    expect(textOf(story)).toContain("Step done");

    // Steps: "Step n of m", and the tab counts what is done
    expect(textOf(tabNamed(rig.el, "Steps"))).toBe("Steps1/3");
    click(tabNamed(rig.el, "Steps"));
    const steps = panel(rig.el, "Steps");
    expect(steps.hidden).toBe(false);
    expect(story.hidden).toBe(true);
    const rows = [...steps.querySelectorAll("li")].map((li) => textOf(li));
    expect(rows).toHaveLength(3);
    expect(rows[0]).toContain("Step 1 of 3");
    expect(rows[0]).toContain("Done");
    expect(rows[1]).toContain("Step 2 of 3");
    expect(rows[2]).toContain("Not started yet");
    expect(textOf(steps)).toContain("1 of 3 done");

    // Result: nothing delivered yet, and it says so
    click(tabNamed(rig.el, "Result"));
    expect(textOf(panel(rig.el, "Result"))).toContain("No result yet");
    expect(rig.el.querySelector('[data-testid="run-result"]')).toBeNull();
  });

  it("STUDIO_3_world_result_tab_reads_the_delivered_result_with_download_and_share", async () => {
    const { client, emit } = liveFeed();
    const rig = await mountWorld({ id: "hires", api: api(), client });
    await emit(
      ...RUN(),
      ev("artifact.delivered", "The plan is ready in Tilo.", {
        artifact: {},
        format: "in_app",
        outbox_id: null,
      }),
      ev("world.completed", "Done.", { credits_used: 4, deliverable_count: 1 }),
    );
    // once the result is delivered the page opens on it
    const result = panel(rig.el, "Result");
    expect(result.hidden).toBe(false);
    expect(result.querySelector('[data-testid="result-text"] h3')?.textContent).toBe("Road trip");
    const clicks: HTMLAnchorElement[] = [];
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:result");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicks.push(this);
    });
    click(control(result, "Download"));
    expect(clicks[0]?.download).toBe("tilo-result-hires.md");
    // Share is the filled button here; Share to Slack and Share with team sit beside it
    const share = control(result, "Share") as HTMLButtonElement;
    expect(share.className).toContain("park-btn--primary");
    expect(control(result, "Share to Slack")).toBeTruthy();
  });

  it("STUDIO_3_world_failed_world_shows_reason_and_start_it_again", async () => {
    const start = vi.fn(async () => ({ world_id: "w_new", task_id: "t_new" }));
    const { client, emit } = liveFeed();
    client.startAgain = start;
    const rig = await mountWorld({ id: "hires", api: api(), client });
    await emit(
      ...RUN(),
      ev("world.failed", "Stopped: the stays tool is not connected", {
        reason: "the stays tool is not connected",
        unit: "U2",
      }),
    );
    const failed = rig.el.querySelector('[data-testid="run-failed"]') as HTMLElement;
    expect(textOf(failed)).toContain("Why: the stays tool is not connected");
    expect(rig.el.querySelector(".park-world-chip")?.textContent).toContain("Stopped");
    expect(textOf(rig.el.querySelector(".park-world-headprog") as Element)).toContain("Stopped");
    click(tabNamed(rig.el, "Steps"));
    expect(textOf(panel(rig.el, "Steps"))).toContain("Stopped here");
    click(tabNamed(rig.el, "Result"));
    expect(textOf(panel(rig.el, "Result"))).toContain(
      "This run stopped before it delivered anything.",
    );
    // Start it again is the one filled button the person sees
    const visiblePrimary = [...rig.el.querySelectorAll(".park-btn--primary")].filter(
      (b) => !b.closest("[hidden]"),
    );
    expect(visiblePrimary.map((b) => textOf(b))).toEqual(["Start it again"]);
    click(control(rig.el, "Start it again"));
    await settle();
    expect(start).toHaveBeenCalledWith("hires");
    expect(rig.app.go).toHaveBeenCalledWith("world", { id: "w_new" });
  });

  it("STUDIO_3_world_assumed_chips_sit_beside_the_tabs", async () => {
    const { client, emit } = liveFeed();
    const rig = await mountWorld({ id: "hires", api: api(), client });
    await emit(...RUN(), ev("agent.working", "Assumed: you travel by car", { unit: "U2" }));
    const row = rig.el.querySelector(".park-world-tabrow") as HTMLElement;
    expect([...row.querySelectorAll(".park-world-assumedchip")].map((c) => textOf(c))).toEqual([
      "Assumed: you travel by car",
    ]);
  });
});

describe("STUDIO_3 the World page: tabs, layout and the one filled button", () => {
  it("STUDIO_3_world_tabs_follow_the_arrow_keys", async () => {
    const rig = await mountWorld();
    const story = tabNamed(rig.el, "Story");
    act(() => {
      story.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    expect(tabNamed(rig.el, "Steps").getAttribute("aria-selected")).toBe("true");
    expect(tabNamed(rig.el, "Steps").tabIndex).toBe(0);
    expect(tabNamed(rig.el, "Story").tabIndex).toBe(-1);
    act(() => {
      tabNamed(rig.el, "Steps").dispatchEvent(
        new KeyboardEvent("keydown", { key: "End", bubbles: true }),
      );
    });
    expect(tabNamed(rig.el, "Result").getAttribute("aria-selected")).toBe("true");
  });

  it("STUDIO_3_world_a_sample_world_keeps_its_story_steps_and_result_from_its_own_data", async () => {
    const city = await mountWorld({ id: "k1" });
    expect(panel(city.el, "Story").querySelector('section[aria-label="Activity"]')).not.toBeNull();
    expect(panel(city.el, "Steps").querySelector('section[aria-label="Districts"]')).not.toBeNull();
    cleanup();
    const village = await mountWorld({ id: "calls" });
    expect(
      panel(village.el, "Result").querySelector('section[aria-label="Result"]'),
    ).not.toBeNull();
  });

  it("STUDIO_3_world_at_most_one_filled_button_is_visible_in_each_tab", async () => {
    for (const id of ["k1", "northline", "calls", "comp"]) {
      const rig = await mountWorld({ id });
      for (const name of ["Story", "Steps", "Result"]) {
        click(tabNamed(rig.el, name));
        const shown = [...rig.el.querySelectorAll(".park-btn--primary")].filter(
          (b) => !b.closest("[hidden]"),
        );
        expect(shown.length, `${id} ${name}`).toBeLessThanOrEqual(1);
      }
      cleanup();
    }
  });

  it("STUDIO_3_world_the_phone_stacks_the_city_above_the_tabs", async () => {
    const rig = await mountWorld({ app: { vw: 390 } });
    const top = rig.el.querySelector(".park-world-top") as HTMLElement;
    expect(top.style.getPropertyValue("grid-template-columns").replace(/\s+/g, "")).toBe(
      "minmax(0,1fr)",
    );
    const [first, second] = [...top.children];
    expect(first?.classList.contains("park-world-mapcard")).toBe(true);
    expect(second?.querySelector('[role="tabpanel"]')).not.toBeNull();
  });

  it("STUDIO_3_world_the_studio_primary_is_the_theme_pair", () => {
    // the filled button is the shared component's primary; the Studio theme paints it priFill / onPri
    expect(readComponentsCss()).toMatch(/\.park-btn--primary/);
  });
});
