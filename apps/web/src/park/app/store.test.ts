// WEB-3a: the framework-free shell store (README "State and data", prototype class in
// `Tilo App.dc.html`: decide, undo, addWorld, toast, go, needsLeft). Pinned surface, park/app/store.ts:
//   type Schedule = (fn: () => void, ms: number) => () => void       (returns the cancel function)
//   realSchedule: Schedule                                            (setTimeout / clearTimeout)
//   createParkStore({ api, navigate, schedule, now? }): ParkStore
//   ParkStore = { getState(): ParkState; subscribe(l: () => void): () => void;
//                 decide(key); undo(key); addWorld(mode, query): World; toast(msg, label?, action?);
//                 dismissToast(); setPref(key, value); go(page, params?); markRead(); noteSource(source) }
//   ParkState = { dec, added, prefs, toast: { message, actionLabel?, action? } | null, read, menu, wl,
//                 time, motion, sources: { fixture, live }, needsLeft }   (needsLeft is derived state)
// Defaults taken where the spec is silent (listed in the WEB-3a report): `added` is newest first (the
// prototype prepends); motion defaults to "lively" (the spec; the prototype says "calm"); the store
// forwards setPref to api.setPref; `now` is accepted and unused by these tests.
import fc from "fast-check";
import { afterEach, describe, expect, it, vi } from "vitest";
import { deepFreeze, fakeApi, fakeScheduler } from "../../../test-support/park/appHarness";
import { decisions } from "../api/fixtures/decisions";
import { TIERS } from "../api/fixtures/index";
import { makeWorld, needsLeft } from "../api/fixtures/worlds";
import { TOAST_MS } from "../components/Toast";
import { createParkStore, realSchedule } from "./store";

function setup() {
  const api = fakeApi();
  const navigate = vi.fn();
  const sch = fakeScheduler();
  const store = createParkStore({ api, navigate, schedule: sch.schedule, now: () => 0 });
  store.setDecisions(decisions); // what the shell hands over once the Api has returned them (WEB-3b)
  return { api, navigate, sch, store };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("WEB_3a_store: initial state and subscription", () => {
  it("WEB_3a_store_initial_state_is_the_prototypes", () => {
    const { store } = setup();
    expect(store.getState()).toMatchObject({
      dec: {},
      added: [],
      prefs: {},
      toast: null,
      read: false,
      menu: null,
      wl: null,
      time: "day",
      motion: "lively",
      needsLeft: 2,
      sources: { fixture: false, live: false },
    });
  });

  it("WEB_3a_store_getState_is_the_same_object_until_something_changes", () => {
    const { store } = setup();
    expect(store.getState()).toBe(store.getState());
    const before = store.getState();
    store.markRead();
    expect(store.getState()).not.toBe(before);
  });

  it("WEB_3a_store_subscribers_hear_each_change_and_stop_after_unsubscribe", () => {
    const { store } = setup();
    const heard = vi.fn();
    const off = store.subscribe(heard);
    store.markRead();
    expect(heard).toHaveBeenCalledTimes(1);
    off();
    store.setPref("time", "night");
    expect(heard).toHaveBeenCalledTimes(1);
  });
});

describe("WEB_3a_store: decide and undo", () => {
  it("WEB_3a_store_decide_depot_approves_calls_the_api_and_toasts_with_undo", () => {
    const { store, api } = setup();
    store.decide("depot");
    expect(store.getState().dec.depot).toBe(true);
    expect(api.decide).toHaveBeenCalledTimes(1);
    expect(api.decide).toHaveBeenCalledWith("depot");
    expect(store.getState().toast).toMatchObject({
      message: "Approved £3,420 for Laptop Depot",
      actionLabel: "Undo",
    });
  });

  it("WEB_3a_store_decide_mail_toasts_the_supplier_brief", () => {
    const { store, api } = setup();
    store.decide("mail");
    expect(store.getState().dec.mail).toBe(true);
    expect(api.decide).toHaveBeenCalledWith("mail");
    expect(store.getState().toast).toMatchObject({
      message: "Supplier brief sent to 3 suppliers",
      actionLabel: "Undo",
    });
  });

  it("WEB_3a_store_needsLeft_follows_the_fixtures_needsLeft", () => {
    const { store } = setup();
    expect(store.getState().needsLeft).toBe(needsLeft({}));
    store.decide("depot");
    expect(store.getState().needsLeft).toBe(1);
    expect(store.getState().needsLeft).toBe(needsLeft(store.getState().dec));
    store.decide("mail");
    expect(store.getState().needsLeft).toBe(0);
    expect(store.getState().needsLeft).toBe(needsLeft(store.getState().dec));
  });

  it("WEB_3a_store_decide_is_idempotent_no_second_api_call_no_second_toast", () => {
    const { store, api, sch } = setup();
    store.decide("depot");
    const toastAfterFirst = store.getState().toast;
    const heard = vi.fn();
    store.subscribe(heard);
    store.decide("depot");
    expect(api.decide).toHaveBeenCalledTimes(1);
    expect(sch.schedule).toHaveBeenCalledTimes(1);
    expect(store.getState().toast).toBe(toastAfterFirst);
    expect(heard).not.toHaveBeenCalled();
  });

  it("WEB_3a_store_a_repeat_decide_leaves_the_other_decisions_toast_alone", () => {
    const { store } = setup();
    store.decide("depot");
    store.decide("mail");
    store.decide("depot");
    expect(store.getState().toast?.message).toBe("Supplier brief sent to 3 suppliers");
  });

  it("WEB_3a_store_the_toast_action_undoes_the_decision", () => {
    const { store, api, sch } = setup();
    store.decide("depot");
    store.getState().toast?.action?.();
    expect(store.getState().dec.depot).toBe(false);
    expect(api.undo).toHaveBeenCalledTimes(1);
    expect(api.undo).toHaveBeenCalledWith("depot");
    expect(store.getState().toast).toBeNull();
    expect(sch.live()).toEqual([]);
    expect(store.getState().needsLeft).toBe(2);
  });

  it("WEB_3a_store_undo_resets_only_its_own_key", () => {
    const { store } = setup();
    store.decide("depot");
    store.decide("mail");
    store.undo("mail");
    expect(store.getState().dec).toMatchObject({ depot: true, mail: false });
    expect(store.getState().needsLeft).toBe(1);
  });

  it("WEB_3a_store_after_an_undo_the_same_decision_can_be_made_again", () => {
    const { store, api } = setup();
    store.decide("depot");
    store.undo("depot");
    store.decide("depot");
    expect(api.decide).toHaveBeenCalledTimes(2);
    expect(store.getState().dec.depot).toBe(true);
    expect(store.getState().toast?.message).toBe("Approved £3,420 for Laptop Depot");
  });

  it("WEB_3a_store_a_rejecting_api_does_not_throw_out_of_decide_or_undo", async () => {
    const { store, api } = setup();
    api.decide.mockRejectedValue(new Error("offline"));
    api.undo.mockRejectedValue(new Error("offline"));
    expect(() => store.decide("depot")).not.toThrow();
    expect(() => store.undo("depot")).not.toThrow();
    await Promise.resolve();
    await Promise.resolve(); // an unhandled rejection would fail the run
  });
});

describe("WEB_3a_store: the toast and its one timer", () => {
  it("WEB_3a_store_TOAST_MS_is_4200", () => {
    expect(TOAST_MS).toBe(4200);
  });

  it("WEB_3a_store_a_toast_is_scheduled_for_TOAST_MS_and_hides_when_it_fires", () => {
    const { store, sch } = setup();
    store.toast("Saved");
    expect(sch.schedule).toHaveBeenCalledTimes(1);
    expect(sch.schedule).toHaveBeenCalledWith(expect.any(Function), 4200);
    expect(store.getState().toast).toMatchObject({ message: "Saved" });
    sch.fire(sch.timers[0]);
    expect(store.getState().toast).toBeNull();
  });

  it("WEB_3a_store_a_toast_without_an_action_has_no_label", () => {
    const { store } = setup();
    store.toast("This is a prototype, so you stay signed in");
    const t = store.getState().toast;
    expect(t?.message).toBe("This is a prototype, so you stay signed in");
    expect(t?.actionLabel).toBeUndefined();
  });

  it("WEB_3a_store_a_toast_action_is_the_callers_function", () => {
    const { store } = setup();
    const act = vi.fn();
    store.toast("Saved", "Open", act);
    expect(store.getState().toast?.actionLabel).toBe("Open");
    store.getState().toast?.action?.();
    expect(act).toHaveBeenCalledTimes(1);
  });

  it("WEB_3a_store_a_new_toast_cancels_the_previous_timer", () => {
    const { store, sch } = setup();
    store.toast("first");
    store.toast("second");
    expect(sch.timers).toHaveLength(2);
    expect(sch.timers[0]?.cancelled).toBe(true);
    expect(sch.timers[1]?.cancelled).toBe(false);
    expect(store.getState().toast?.message).toBe("second");
    expect(sch.timers[1]?.ms).toBe(4200);
  });

  it("WEB_3a_store_dismissToast_cancels_the_timer_and_clears_the_toast", () => {
    const { store, sch } = setup();
    store.toast("Saved");
    store.dismissToast();
    expect(store.getState().toast).toBeNull();
    expect(sch.timers[0]?.cancelled).toBe(true);
  });

  it("WEB_3a_store_dismissToast_with_no_toast_is_harmless", () => {
    const { store } = setup();
    const heard = vi.fn();
    store.subscribe(heard);
    expect(() => store.dismissToast()).not.toThrow();
    expect(store.getState().toast).toBeNull();
    expect(heard).not.toHaveBeenCalled();
  });

  it("WEB_3a_store_undo_cancels_the_timer", () => {
    const { store, sch } = setup();
    store.decide("mail");
    store.undo("mail");
    expect(sch.timers[0]?.cancelled).toBe(true);
    expect(store.getState().toast).toBeNull();
  });

  it("WEB_3a_store_the_real_scheduler_is_setTimeout_and_returns_its_cancel", () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    const cancel = realSchedule(fn, 4200);
    vi.advanceTimersByTime(4199);
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledTimes(1);
    const fn2 = vi.fn();
    const cancel2 = realSchedule(fn2, 100);
    cancel2();
    vi.advanceTimersByTime(1000);
    expect(fn2).not.toHaveBeenCalled();
    expect(() => cancel()).not.toThrow();
  });
});

describe("WEB_3a_store: addWorld", () => {
  it("WEB_3a_store_addWorld_returns_the_fixtures_world_and_keeps_it", () => {
    const { store } = setup();
    const w = store.addWorld("quick", "Order lunch");
    expect(w).toEqual(makeWorld("quick", "Order lunch", 1));
    expect(w.id).toBe("new1");
    expect(store.getState().added).toEqual([w]);
  });

  it("WEB_3a_store_addWorld_numbers_by_added_length_and_puts_the_newest_first", () => {
    const { store } = setup();
    store.addWorld("quick", "One");
    const second = store.addWorld("routine", "Two");
    expect(second.id).toBe("new2");
    expect(second).toEqual(makeWorld("routine", "Two", 2));
    expect(store.getState().added.map((w) => w.id)).toEqual(["new2", "new1"]);
  });

  it("WEB_3a_store_addWorld_with_no_query_uses_the_tier_placeholder_in_every_mode", () => {
    for (const mode of ["quick", "routine", "workspace"] as const) {
      const { store } = setup();
      const w = store.addWorld(mode, "");
      expect(w.name, mode).toBe(TIERS[mode].ph);
      expect(w, mode).toEqual(makeWorld(mode, "", 1));
    }
  });

  it("WEB_3a_store_addWorld_toasts_Started_with_the_short_name_and_Open", () => {
    const { store } = setup();
    store.addWorld("quick", "Order lunch");
    expect(store.getState().toast).toMatchObject({
      message: "Started “Order lunch”",
      actionLabel: "Open",
    });
  });

  it("WEB_3a_store_addWorld_toast_uses_the_shortened_name_for_a_long_query", () => {
    const { store } = setup();
    const long = "Summarise this week’s customer feedback for every region";
    const w = store.addWorld("quick", long);
    expect(w.short.endsWith("…")).toBe(true);
    expect(store.getState().toast?.message).toBe(`Started “${w.short}”`);
  });

  it("WEB_3a_store_the_Open_action_goes_to_the_new_world_and_clears_the_toast", () => {
    const { store, navigate } = setup();
    store.addWorld("quick", "Order lunch");
    store.getState().toast?.action?.();
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/world/new1");
    expect(store.getState().toast).toBeNull();
  });
});

describe("WEB_3a_store: prefs, time and motion", () => {
  it("WEB_3a_store_setPref_time_night_derives_time_night", () => {
    const { store } = setup();
    store.setPref("time", "night");
    expect(store.getState().prefs.time).toBe("night");
    expect(store.getState().time).toBe("night");
    store.setPref("time", "day");
    expect(store.getState().time).toBe("day");
  });

  it("WEB_3a_store_any_other_time_value_is_day", () => {
    const { store } = setup();
    store.setPref("time", "night");
    store.setPref("time", "dusk");
    expect(store.getState().time).toBe("day");
  });

  it("WEB_3a_store_setPref_motion_takes_lively_calm_and_still", () => {
    for (const m of ["lively", "calm", "still"] as const) {
      const { store } = setup();
      store.setPref("motion", m);
      expect(store.getState().motion).toBe(m);
    }
  });

  it("WEB_3a_store_motion_defaults_to_lively_and_an_unknown_value_falls_back_to_it", () => {
    const { store } = setup();
    expect(store.getState().motion).toBe("lively");
    store.setPref("motion", "wild");
    expect(store.getState().motion).toBe("lively");
  });

  it("WEB_3a_store_prefs_keep_backup_for_the_ledger_beside_other_keys", () => {
    const { store } = setup();
    store.setPref("backup", "p2");
    store.setPref("time", "night");
    expect(store.getState().prefs).toEqual({ backup: "p2", time: "night" });
  });

  it("WEB_3a_store_setPref_is_forwarded_to_the_api", () => {
    const { store, api } = setup();
    store.setPref("backup", "p2");
    expect(api.setPref).toHaveBeenCalledWith("backup", "p2");
  });
});

describe("WEB_3a_store: navigation, read and sources", () => {
  it("WEB_3a_store_go_navigates_to_the_park_path", () => {
    const table = [
      ["home", undefined, "/"],
      ["worlds", undefined, "/worlds"],
      ["world", { id: "k1" }, "/world/k1"],
      ["skills", { id: "sk2" }, "/skills?id=sk2"],
      ["team", { focus: "share" }, "/team?focus=share"],
      ["profile", { tab: "notifications" }, "/profile?tab=notifications"],
      ["ledger", { x: "1" }, "/ledger"],
    ] as const;
    for (const [page, params, path] of table) {
      const { store, navigate } = setup();
      store.go(page, params as Record<string, string> | undefined);
      expect(navigate).toHaveBeenCalledTimes(1);
      expect(navigate).toHaveBeenCalledWith(path);
    }
  });

  it("WEB_3a_store_markRead_sets_read_once", () => {
    const { store } = setup();
    const heard = vi.fn();
    store.subscribe(heard);
    store.markRead();
    store.markRead();
    expect(store.getState().read).toBe(true);
    expect(heard).toHaveBeenCalledTimes(1);
  });

  it("WEB_3a_store_noteSource_fixture_and_live_are_recorded_separately", () => {
    const { store } = setup();
    store.noteSource("fixture");
    expect(store.getState().sources).toEqual({ fixture: true, live: false });
    store.noteSource("live");
    expect(store.getState().sources).toEqual({ fixture: true, live: true });
  });

  it("WEB_3a_store_noteSource_repeats_do_not_notify", () => {
    const { store } = setup();
    store.noteSource("fixture");
    const heard = vi.fn();
    store.subscribe(heard);
    store.noteSource("fixture");
    expect(heard).not.toHaveBeenCalled();
  });
});

describe("WEB_3a_store: state is replaced, never mutated", () => {
  it("WEB_3a_store_a_frozen_snapshot_survives_every_action", () => {
    const { store } = setup();
    const snapshots = [store.getState()];
    const steps: (() => void)[] = [
      () => store.decide("depot"),
      () => store.decide("mail"),
      () => store.undo("mail"),
      () => store.addWorld("quick", "A"),
      () => store.addWorld("workspace", "B"),
      () => store.setPref("time", "night"),
      () => store.setPref("backup", "p2"),
      () => store.toast("hi", "Ok", () => undefined),
      () => store.markRead(),
      () => store.noteSource("fixture"),
      () => store.dismissToast(),
    ];
    for (const step of steps) {
      deepFreeze(store.getState());
      expect(step).not.toThrow(); // writing to a frozen object throws in strict mode
      snapshots.push(store.getState());
    }
    expect(snapshots[0]).toMatchObject({ dec: {}, added: [], prefs: {}, read: false });
    expect(snapshots[0]?.sources).toEqual({ fixture: false, live: false });
  });

  it("WEB_3a_store_each_change_gives_new_dec_added_prefs_and_sources_objects", () => {
    const { store } = setup();
    const a = store.getState();
    store.decide("depot");
    store.addWorld("quick", "A");
    store.setPref("time", "night");
    store.noteSource("live");
    const b = store.getState();
    expect(b.dec).not.toBe(a.dec);
    expect(b.added).not.toBe(a.added);
    expect(b.prefs).not.toBe(a.prefs);
    expect(b.sources).not.toBe(a.sources);
    expect(a.dec).toEqual({});
    expect(a.added).toEqual([]);
  });
});

describe("WEB_3a_store: properties over random action sequences", () => {
  type Cmd =
    | { t: "decide" | "undo"; k: "depot" | "mail" }
    | { t: "add"; mode: "quick" | "routine" | "workspace"; q: string }
    | { t: "pref"; key: "time" | "motion" | "backup"; v: string }
    | { t: "toast" }
    | { t: "dismiss" }
    | { t: "fire" }
    | { t: "toastAction" };
  const cmd: fc.Arbitrary<Cmd> = fc.oneof(
    fc.record({
      t: fc.constantFrom("decide", "undo"),
      k: fc.constantFrom("depot", "mail"),
    }),
    fc.record({
      t: fc.constant("add" as const),
      mode: fc.constantFrom("quick", "routine", "workspace"),
      q: fc.string({ maxLength: 40 }),
    }),
    fc.record({
      t: fc.constant("pref" as const),
      key: fc.constantFrom("time", "motion", "backup"),
      v: fc.constantFrom("night", "day", "still", "calm", "lively", "x", "p2"),
    }),
    fc.constant({ t: "toast" as const }),
    fc.constant({ t: "dismiss" as const }),
    fc.constant({ t: "fire" as const }),
    fc.constant({ t: "toastAction" as const }),
  );

  it("WEB_3a_store_property_invariants_hold_after_any_sequence", () => {
    fc.assert(
      fc.property(fc.array(cmd, { maxLength: 40 }), (cmds) => {
        const { store, sch } = setup();
        for (const c of cmds) {
          if (c.t === "decide") store.decide(c.k);
          else if (c.t === "undo") store.undo(c.k);
          else if (c.t === "add") store.addWorld(c.mode, c.q);
          else if (c.t === "pref") store.setPref(c.key, c.v);
          else if (c.t === "toast") store.toast("note");
          else if (c.t === "dismiss") store.dismissToast();
          else if (c.t === "toastAction") store.getState().toast?.action?.();
          else sch.fire(sch.live()[0]);

          const s = store.getState();
          // needsLeft is the fixtures' count, so between 0 and the number of decisions
          expect(s.needsLeft).toBe(decisions.filter((d) => !s.dec[d.k]).length);
          // one toast at a time, and a toast is on screen exactly while its one timer is alive
          expect(sch.live().length).toBeLessThanOrEqual(1);
          expect(s.toast !== null).toBe(sch.live().length === 1);
          // time is derived from prefs.time, motion is always one of the three
          expect(s.time).toBe(s.prefs.time === "night" ? "night" : "day");
          expect(["lively", "calm", "still"]).toContain(s.motion);
          // started worlds are numbered 1..n, newest first, with no duplicate id
          expect(s.added.map((w) => w.id)).toEqual(
            s.added.map((_, i) => `new${s.added.length - i}`),
          );
        }
      }),
    );
  });
});
