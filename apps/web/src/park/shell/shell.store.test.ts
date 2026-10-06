// WEB-3b: what the shell adds to the WEB-3a store (park/app/store.ts): `openWorld(id)`, the prototype's
// `openWorld` in `Tilo App.dc.html` ("Opening a world always runs the WorldLoader first").
// The one pinned addition: `ParkStore.openWorld(id: string): void`, using the `wl` field WEB-3a already holds
// (`{ id, step }` or null):
//   - a known world: wl = { id, step: 0 } and any open menu closes; then ONE injected `schedule(fn, ms)` per
//     step, ms = 340 for a City world and 250 for a Town or Village; step 1 and 2 only advance wl; at the
//     third tick (step 3) the page swaps in (navigate to /park/world/<id>) and all three steps read done; the
//     fourth tick removes the card (wl = null) and leaves nothing scheduled;
//   - an unknown id shows no loader and `go` still goes to the page (which then handles not found);
//   - opening another world restarts the loader and the old timer is cancelled.
// Opening a menu is done through the UI in the component tests (the 3a state already holds `menu`).
import { describe, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler } from "../../../test-support/park/appHarness";
import { createParkStore } from "../app/store";

function setup() {
  const api = fakeApi();
  const navigate = vi.fn();
  const sch = fakeScheduler();
  const store = createParkStore({ api, navigate, schedule: sch.schedule, now: () => 0 });
  return { navigate, sch, store };
}
const tickAll = (sch: ReturnType<typeof setup>["sch"], n: number) => {
  for (let i = 0; i < n; i++) sch.fire(sch.live()[0]);
};

describe("WEB_3b_loader_store: openWorld runs the loader", () => {
  it("WEB_3b_loader_store_a_city_starts_at_step_0_scheduled_340_ms_and_the_page_has_not_moved", () => {
    const { store, navigate, sch } = setup();
    store.openWorld("k1");
    expect(store.getState().wl).toEqual({ id: "k1", step: 0 });
    expect(sch.schedule).toHaveBeenCalledTimes(1);
    expect(sch.schedule).toHaveBeenLastCalledWith(expect.any(Function), 340);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("WEB_3b_loader_store_a_city_steps_every_340_ms_and_swaps_the_page_at_step_3", () => {
    const { store, navigate, sch } = setup();
    store.openWorld("k1");
    tickAll(sch, 1);
    expect(store.getState().wl).toEqual({ id: "k1", step: 1 });
    tickAll(sch, 1);
    expect(store.getState().wl).toEqual({ id: "k1", step: 2 });
    expect(navigate).not.toHaveBeenCalled();
    tickAll(sch, 1);
    expect(store.getState().wl).toEqual({ id: "k1", step: 3 });
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/park/world/k1");
    expect(sch.timers.map((t) => t.ms)).toEqual([340, 340, 340, 340]);
  });

  it("WEB_3b_loader_store_the_card_goes_on_the_fourth_tick_and_nothing_stays_scheduled", () => {
    const { store, navigate, sch } = setup();
    store.openWorld("k1");
    tickAll(sch, 4);
    expect(store.getState().wl).toBeNull();
    expect(sch.live()).toEqual([]);
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("WEB_3b_loader_store_a_town_steps_every_250_ms", () => {
    const { store, sch } = setup();
    store.openWorld("northline");
    expect(store.getState().wl).toEqual({ id: "northline", step: 0 });
    tickAll(sch, 4);
    expect(sch.timers.map((t) => t.ms)).toEqual([250, 250, 250, 250]);
  });

  it("WEB_3b_loader_store_a_village_steps_every_250_ms", () => {
    const { store, sch } = setup();
    store.openWorld("comp");
    tickAll(sch, 4);
    expect(sch.timers.map((t) => t.ms)).toEqual([250, 250, 250, 250]);
  });

  it("WEB_3b_loader_store_a_world_the_user_started_loads_at_the_pace_of_its_size", () => {
    for (const [mode, ms] of [
      ["workspace", 340],
      ["routine", 250],
      ["quick", 250],
    ] as const) {
      const { store, sch } = setup();
      const w = store.addWorld(mode, "A job");
      const armed = sch.timers.length; // the Started toast has its own timer
      store.openWorld(w.id);
      expect(store.getState().wl, mode).toEqual({ id: w.id, step: 0 });
      expect(sch.timers[armed]?.ms, mode).toBe(ms);
    }
  });

  it("WEB_3b_loader_store_an_unknown_id_shows_no_loader_and_go_still_goes_to_the_page", () => {
    const { store, navigate, sch } = setup();
    store.openWorld("nope");
    expect(store.getState().wl).toBeNull();
    expect(sch.schedule).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/park/world/nope");
  });

  it("WEB_3b_loader_store_opening_another_world_restarts_and_the_old_timer_is_dead", () => {
    const { store, navigate, sch } = setup();
    store.openWorld("k1");
    const first = sch.timers[0];
    store.openWorld("comp");
    expect(first?.cancelled).toBe(true);
    expect(store.getState().wl).toEqual({ id: "comp", step: 0 });
    sch.fire(first); // a cancelled timer never runs
    expect(store.getState().wl).toEqual({ id: "comp", step: 0 });
    tickAll(sch, 4);
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/park/world/comp");
  });

  it("WEB_3b_loader_store_it_leaves_the_toast_timer_alone", () => {
    const { store, sch } = setup();
    store.toast("Saved");
    store.openWorld("comp");
    expect(sch.live()).toHaveLength(2);
    expect(store.getState().toast?.message).toBe("Saved");
  });

  it("WEB_3b_loader_store_every_step_notifies_subscribers", () => {
    const { store, sch } = setup();
    store.openWorld("comp");
    const heard = vi.fn();
    store.subscribe(heard);
    tickAll(sch, 4);
    expect(heard.mock.calls.length).toBeGreaterThanOrEqual(4);
  });
});
