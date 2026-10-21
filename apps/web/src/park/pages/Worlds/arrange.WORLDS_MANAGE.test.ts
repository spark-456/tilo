// WORLDS-MANAGE: the pure rules behind sort, pin and delete on the Worlds page.
import { describe, expect, it } from "vitest";
import type { World } from "../../api/types";
import { arrange, deletable, deleteSummary, stillWorking } from "./arrange";
import { STATUS_TABS, STOPPED_TAB, countFor, statusOf, visibleWorlds } from "./model";

const world = (id: string, over: Partial<World> = {}): World =>
  ({
    id,
    name: id,
    short: id,
    tier: "Village",
    tool: "",
    st: "finished",
    agents: 0,
    spend: "",
    spendV: 0,
    nextL: "",
    nextV: "",
    owner: "",
    started: "",
    ...over,
  }) as World;

const ids = (ws: readonly World[]) => ws.map((w) => w.id);

describe("WORLDS_MANAGE arrange", () => {
  const list = [
    world("b", { name: "Bravo", st: "finished", started: "2026-10-01T09:00:00Z" }),
    world("a", { name: "alpha", st: "running", started: "2026-10-20T09:00:00Z" }),
    world("c", { name: "Charlie", st: "needs", started: "" }),
  ];

  it("WORLDS_MANAGE_sorts_by_status_newest_oldest_and_name", () => {
    expect(ids(arrange(list, "status", new Set()))).toEqual(["c", "a", "b"]);
    expect(ids(arrange(list, "newest", new Set()))).toEqual(["a", "b", "c"]); // no date sorts last
    expect(ids(arrange(list, "oldest", new Set()))).toEqual(["b", "a", "c"]);
    expect(ids(arrange(list, "name", new Set()))).toEqual(["a", "b", "c"]); // case-insensitive
  });

  it("WORLDS_MANAGE_pinned_worlds_come_first_in_the_chosen_order", () => {
    expect(ids(arrange(list, "name", new Set(["c", "b"])))).toEqual(["b", "c", "a"]);
  });

  it("WORLDS_MANAGE_only_the_persons_own_worlds_are_deletable", () => {
    expect(deletable(world("mine"))).toBe(true);
    expect(deletable(world("team", { access: "team" }))).toBe(false);
    expect(deletable(world("sample", { sample: true }))).toBe(false);
    expect(stillWorking(world("r", { st: "running" }))).toBe(true);
    expect(stillWorking(world("d", { st: "finished" }))).toBe(false);
  });

  it("WORLDS_MANAGE_the_dialog_names_one_world_and_counts_many", () => {
    expect(deleteSummary([world("x", { name: "K1 electric scooter" })]).title).toBe(
      "Delete “K1 electric scooter”?",
    );
    expect(deleteSummary([world("x"), world("y", { st: "running" })])).toEqual({
      title: "Delete 2 worlds?",
      working: 1,
    });
  });
});

describe("WORLDS_MANAGE stopped worlds", () => {
  const all = [world("done"), world("stop", { stopped: true }), world("run", { st: "running" })];

  it("WORLDS_MANAGE_a_served_stop_is_its_own_tab_not_done", () => {
    expect(STATUS_TABS).toHaveLength(5); // the five design tabs stay; Stopped is added only when needed
    expect(STOPPED_TAB[1]).toBe("Stopped");
    expect(countFor(all, "", "all", "stopped")).toBe(1);
    expect(countFor(all, "", "all", "finished")).toBe(1);
    expect(ids(visibleWorlds(all, "", "all", "stopped"))).toEqual(["stop"]);
    expect(statusOf(all[1] as World, 0)).toEqual({ label: "Stopped", tone: "stop" });
  });
});
