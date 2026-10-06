// WEB-3b: what the shell adds to the WEB-3a store (park/app/store.ts). Pinned additions, nothing else changes:
//   ParkState.wl: { id: string; step: number } | null   (step 0..3; null = no loader)
//   ParkState.pins: readonly { x: number; y: number }[]  (initially []; fed by the backdrop; useApp().pins reads it)
//   ParkStore.openWorld(id)      the world loader: wl = { id, step: 0 }, menu closed, then the page swaps in
//                                at step 3 and the loader ends at step 4; one injected `schedule(fn, ms)` per
//                                step, ms = 340 for a City world, 250 for a Town or Village (prototype openWorld)
//   ParkStore.toggleMenu(which)  "notif" | "acct": opens it, or closes it when it is the open one; opening
//                                "notif" marks the notifications read (prototype toggleNotif)
//   ParkStore.closeMenu()        menu = null (a no-op that does not notify when already closed)
//   ParkStore.setPins(pins)      replaces the pins; an equal list does not notify
//   ParkStore.go(...)            also closes any open menu (prototype go), and stays the plain navigation the
//                                WEB-3a tests pin: only openWorld shows the loader (see the WEB-3b report).
import { describe, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler } from "../../../test-support/park/appHarness";
import { createParkStore } from "../app/store";

function setup() {
  const api = fakeApi();
  const navigate = vi.fn();
  const sch = fakeScheduler();
  const store = createParkStore({ api, navigate, schedule: sch.schedule, now: () => 0 });
  return { api, navigate, sch, store };
}

describe("WEB_3b_store: the menu", () => {
  it("WEB_3b_store_toggleMenu_notif_opens_and_marks_read", () => {
    const { store } = setup();
    expect(store.getState().menu).toBeNull();
    store.toggleMenu("notif");
    expect(store.getState().menu).toBe("notif");
    expect(store.getState().read).toBe(true);
  });

  it("WEB_3b_store_toggleMenu_twice_closes_and_read_stays_true", () => {
    const { store } = setup();
    store.toggleMenu("notif");
    store.toggleMenu("notif");
    expect(store.getState().menu).toBeNull();
    expect(store.getState().read).toBe(true);
  });

  it("WEB_3b_store_toggleMenu_acct_does_not_mark_read", () => {
    const { store } = setup();
    store.toggleMenu("acct");
    expect(store.getState().menu).toBe("acct");
    expect(store.getState().read).toBe(false);
  });

  it("WEB_3b_store_one_menu_at_a_time", () => {
    const { store } = setup();
    store.toggleMenu("notif");
    store.toggleMenu("acct");
    expect(store.getState().menu).toBe("acct");
    store.toggleMenu("notif");
    expect(store.getState().menu).toBe("notif");
  });

  it("WEB_3b_store_closeMenu_closes_and_is_silent_when_already_closed", () => {
    const { store } = setup();
    store.toggleMenu("acct");
    const heard = vi.fn();
    store.subscribe(heard);
    store.closeMenu();
    expect(store.getState().menu).toBeNull();
    expect(heard).toHaveBeenCalledTimes(1);
    store.closeMenu();
    expect(heard).toHaveBeenCalledTimes(1);
  });

  it("WEB_3b_store_go_closes_the_open_menu_and_still_navigates_at_once", () => {
    const { store, navigate } = setup();
    store.toggleMenu("acct");
    store.go("ledger");
    expect(store.getState().menu).toBeNull();
    expect(navigate).toHaveBeenCalledWith("/park/ledger");
  });

  it("WEB_3b_store_go_world_stays_the_immediate_navigation_the_3a_tests_pin", () => {
    const { store, navigate, sch } = setup();
    store.go("world", { id: "k1" });
    expect(navigate).toHaveBeenCalledWith("/park/world/k1");
    expect(store.getState().wl).toBeNull();
    expect(sch.schedule).not.toHaveBeenCalled();
  });
});

describe("WEB_3b_store: pins", () => {
  it("WEB_3b_store_pins_start_empty_and_setPins_replaces_them", () => {
    const { store } = setup();
    expect(store.getState().pins).toEqual([]);
    store.setPins([
      { x: 1, y: 2 },
      { x: 3, y: 4 },
    ]);
    expect(store.getState().pins).toEqual([
      { x: 1, y: 2 },
      { x: 3, y: 4 },
    ]);
  });

  it("WEB_3b_store_setPins_with_an_equal_list_does_not_notify", () => {
    const { store } = setup();
    store.setPins([{ x: 1, y: 2 }]);
    const heard = vi.fn();
    store.subscribe(heard);
    const before = store.getState();
    store.setPins([{ x: 1, y: 2 }]);
    expect(heard).not.toHaveBeenCalled();
    expect(store.getState()).toBe(before);
    store.setPins([{ x: 1, y: 3 }]);
    expect(heard).toHaveBeenCalledTimes(1);
  });
});

describe("WEB_3b_store: openWorld runs the loader", () => {
  it("WEB_3b_store_openWorld_a_city_sets_wl_step_0_and_schedules_340", () => {
    const { store, navigate, sch } = setup();
    store.toggleMenu("notif");
    store.openWorld("k1");
    expect(store.getState().wl).toEqual({ id: "k1", step: 0 });
    expect(store.getState().menu).toBeNull();
    expect(sch.schedule).toHaveBeenCalledTimes(1);
    expect(sch.schedule).toHaveBeenLastCalledWith(expect.any(Function), 340);
    expect(navigate).not.toHaveBeenCalled(); // the page is still the old one
  });

  it("WEB_3b_store_a_city_steps_at_340_ms_and_swaps_the_page_at_step_3", () => {
    const { store, navigate, sch } = setup();
    store.openWorld("k1");
    sch.fire(sch.live()[0]);
    expect(store.getState().wl).toEqual({ id: "k1", step: 1 });
    sch.fire(sch.live()[0]);
    expect(store.getState().wl).toEqual({ id: "k1", step: 2 });
    expect(navigate).not.toHaveBeenCalled();
    sch.fire(sch.live()[0]);
    expect(store.getState().wl).toEqual({ id: "k1", step: 3 });
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/park/world/k1");
    expect(sch.timers.map((t) => t.ms)).toEqual([340, 340, 340, 340]);
  });

  it("WEB_3b_store_the_card_is_removed_after_the_fourth_tick_and_nothing_stays_scheduled", () => {
    const { store, navigate, sch } = setup();
    store.openWorld("k1");
    for (let i = 0; i < 4; i++) sch.fire(sch.live()[0]);
    expect(store.getState().wl).toBeNull();
    expect(sch.live()).toEqual([]);
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("WEB_3b_store_a_town_steps_at_250_ms", () => {
    const { store, sch } = setup();
    store.openWorld("northline");
    expect(store.getState().wl).toEqual({ id: "northline", step: 0 });
    for (let i = 0; i < 4; i++) sch.fire(sch.live()[0]);
    expect(sch.timers.map((t) => t.ms)).toEqual([250, 250, 250, 250]);
  });

  it("WEB_3b_store_a_village_steps_at_250_ms", () => {
    const { store, sch } = setup();
    store.openWorld("comp");
    for (let i = 0; i < 4; i++) sch.fire(sch.live()[0]);
    expect(sch.timers.map((t) => t.ms)).toEqual([250, 250, 250, 250]);
  });

  it("WEB_3b_store_a_world_the_user_started_opens_by_its_tier", () => {
    const { store, sch } = setup();
    store.addWorld("workspace", "Plan the offsite");
    const sched = sch.schedule.mock.calls.length; // the Started toast timer
    store.openWorld("new1");
    expect(store.getState().wl).toEqual({ id: "new1", step: 0 });
    expect(sch.schedule.mock.calls[sched]?.[1]).toBe(340); // a workspace is a City
  });

  it("WEB_3b_store_an_unknown_id_shows_no_loader_and_go_still_goes_to_the_page", () => {
    const { store, navigate, sch } = setup();
    store.toggleMenu("notif");
    store.openWorld("nope");
    expect(store.getState().wl).toBeNull();
    expect(sch.schedule).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith("/park/world/nope");
    expect(store.getState().menu).toBeNull();
  });

  it("WEB_3b_store_opening_another_world_restarts_the_loader_and_the_old_timer_is_dead", () => {
    const { store, navigate, sch } = setup();
    store.openWorld("k1");
    const first = sch.timers[0];
    store.openWorld("comp");
    expect(first?.cancelled).toBe(true);
    expect(store.getState().wl).toEqual({ id: "comp", step: 0 });
    sch.fire(first);
    expect(store.getState().wl).toEqual({ id: "comp", step: 0 });
    for (let i = 0; i < 4; i++) sch.fire(sch.live()[0]);
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/park/world/comp");
  });

  it("WEB_3b_store_the_loader_timer_leaves_the_toast_timer_alone", () => {
    const { store, sch } = setup();
    store.toast("Saved");
    store.openWorld("comp");
    expect(sch.live()).toHaveLength(2);
    expect(store.getState().toast?.message).toBe("Saved");
  });

  it("WEB_3b_store_each_loader_step_notifies_subscribers", () => {
    const { store, sch } = setup();
    store.openWorld("comp");
    const heard = vi.fn();
    store.subscribe(heard);
    for (let i = 0; i < 4; i++) sch.fire(sch.live()[0]);
    expect(heard.mock.calls.length).toBeGreaterThanOrEqual(4);
  });
});
