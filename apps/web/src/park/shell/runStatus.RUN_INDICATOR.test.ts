// RUN-INDICATOR (PRD 9.4 HR-1, HR-2): what the bottom run bar says is a pure function of the worlds the Api
// served. A run is "in progress" only where the served state says so (`running`); a held run (`needs`, an open
// card) is shown as a static label; every other state (finished, scheduled) and an empty list show nothing.
// There is no progress number anywhere: `prog` is never read.
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import type { ActivityItem, World, WorldState } from "../api/types";
import { runBarOf } from "./runStatus";

const world = (over: Partial<World> = {}): World => ({
  id: "w1",
  name: "Offsite venue options",
  short: "Venue options",
  tier: "Village",
  tool: "Quick task",
  st: "running",
  agents: 0,
  spend: "",
  spendV: 0,
  nextL: "",
  nextV: "",
  owner: "",
  started: "",
  ...over,
});
const act = (text: string): ActivityItem => ({ t: "now", who: "Director", text, kind: "info" });

describe("RUN_INDICATOR logic: nothing recorded, nothing shown", () => {
  it("RUN_INDICATOR_no_worlds_shows_no_bar", () => {
    expect(runBarOf([])).toBeNull();
  });

  it("RUN_INDICATOR_finished_and_scheduled_worlds_show_no_bar", () => {
    expect(runBarOf([world({ st: "finished" }), world({ id: "w2", st: "scheduled" })])).toBeNull();
  });
});

describe("RUN_INDICATOR logic: team worlds are not the person's own work (BQ-CTX-TEAMWORLD)", () => {
  it("RUN_INDICATOR_a_teammates_running_or_held_world_shows_no_bar", () => {
    expect(
      runBarOf([world({ access: "team" }), world({ id: "w2", st: "needs", access: "team" })]),
    ).toBeNull();
  });
  it("RUN_INDICATOR_own_running_world_counts_alone_beside_a_teammates", () => {
    const bar = runBarOf([world({ agents: 2 }), world({ id: "w2", agents: 5, access: "team" })]);
    expect(bar?.label).toBe("2 agents working");
  });
});

describe("RUN_INDICATOR logic: a running world", () => {
  it("RUN_INDICATOR_a_running_world_shows_the_moving_bar_with_an_honest_label", () => {
    const bar = runBarOf([world()]);
    expect(bar?.kind).toBe("running");
    expect(bar?.label).toBe("Working");
    expect(bar?.detail).toBe("Venue options");
  });

  it("RUN_INDICATOR_the_label_counts_the_agents_the_Api_served", () => {
    expect(runBarOf([world({ agents: 3 })])?.label).toBe("3 agents working");
    expect(runBarOf([world({ agents: 1 })])?.label).toBe("1 agent working");
    expect(runBarOf([world({ agents: 2 }), world({ id: "w2", agents: 4 })])?.label).toBe(
      "6 agents working",
    );
  });

  it("RUN_INDICATOR_the_label_follows_the_latest_recorded_activity_line", () => {
    const first = runBarOf([world({ activity: [act("Read your brief and started planning.")] })]);
    expect(first?.detail).toBe("Read your brief and started planning.");
    const next = runBarOf([
      world({ activity: [act("Asked two suppliers for quotes."), act("Read your brief.")] }),
    ]);
    expect(next?.detail).toBe("Asked two suppliers for quotes.");
  });

  it("RUN_INDICATOR_several_running_worlds_are_counted_not_listed", () => {
    expect(runBarOf([world(), world({ id: "w2" }), world({ id: "w3" })])?.detail).toBe("3 worlds");
  });
});

describe("RUN_INDICATOR logic: held runs are static", () => {
  it("RUN_INDICATOR_a_held_run_reads_Waiting_for_your_approval_and_is_not_moving", () => {
    const bar = runBarOf([world({ st: "needs" })]);
    expect(bar?.kind).toBe("held");
    expect(bar?.label).toBe("Waiting for your approval");
  });

  it("RUN_INDICATOR_a_running_world_wins_over_a_held_one", () => {
    const bar = runBarOf([world({ st: "needs" }), world({ id: "w2", st: "running", agents: 2 })]);
    expect(bar?.kind).toBe("running");
    expect(bar?.label).toBe("2 agents working");
  });
});

describe("RUN_INDICATOR logic: no fake progress", () => {
  it("RUN_INDICATOR_no_percentage_and_the_prog_field_is_never_read", () => {
    const states: WorldState[] = ["needs", "running", "finished", "scheduled"];
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            st: fc.constantFrom(...states),
            prog: fc.integer({ min: 0, max: 100 }),
            agents: fc.integer({ min: 0, max: 40 }),
          }),
          { maxLength: 6 },
        ),
        (specs) => {
          const worlds = specs.map((s, i) => world({ id: `w${i}`, ...s }));
          const bar = runBarOf(worlds);
          if (bar) {
            expect(`${bar.label} ${bar.detail ?? ""}`).not.toMatch(/%|percent|\bprog/i);
          }
          // Same worlds with every prog changed: the same bar.
          expect(runBarOf(worlds.map((w) => ({ ...w, prog: 7 })))).toEqual(bar);
        },
      ),
      { numRuns: 60 },
    );
  });
});
