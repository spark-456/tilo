// THROWAWAY (WEB-3b validation only): stand-in for the WEB-3a store plus the WEB-3b additions.
import { decisions } from "../api/fixtures/decisions";
import { makeWorld, needsLeft, worlds } from "../api/fixtures/worlds";
import type { Api } from "../api/index";
import type { Dec, DecisionKey, Source, TierKey, World } from "../api/types";
import { TOAST_MS } from "../components/Toast";
import type { Motion, PageId, Params } from "./AppCtx";
import { parkPath } from "./router";

export type Schedule = (fn: () => void, ms: number) => () => void;
export const realSchedule: Schedule = (fn, ms) => {
  const id = setTimeout(fn, ms);
  return () => clearTimeout(id);
};

export interface ToastState {
  message: string;
  actionLabel: string | undefined;
  action: (() => void) | undefined;
}
export interface Pin {
  x: number;
  y: number;
}
export interface ParkState {
  dec: Dec;
  added: readonly World[];
  prefs: Readonly<Record<string, unknown>>;
  toast: ToastState | null;
  read: boolean;
  menu: "notif" | "acct" | null;
  wl: { id: string; step: number } | null;
  time: "day" | "night";
  motion: Motion;
  sources: { fixture: boolean; live: boolean };
  needsLeft: number;
  pins: readonly Pin[];
}
export interface ParkStore {
  getState(): ParkState;
  subscribe(l: () => void): () => void;
  decide(key: DecisionKey): void;
  undo(key: DecisionKey): void;
  addWorld(mode: TierKey, query: string): World;
  toast(msg: string, label?: string, action?: () => void): void;
  dismissToast(): void;
  setPref(key: string, value: unknown): void;
  go(page: PageId, params?: Params): void;
  markRead(): void;
  noteSource(source: Source): void;
  openWorld(id: string): void;
  toggleMenu(which: "notif" | "acct"): void;
  closeMenu(): void;
  setPins(pins: readonly Pin[]): void;
}

export function createParkStore(deps: {
  api: Api;
  navigate: (to: string) => void;
  schedule: Schedule;
  now?: () => number;
}): ParkStore {
  const { api, navigate, schedule } = deps;
  let state: ParkState = {
    dec: {},
    added: [],
    prefs: {},
    toast: null,
    read: false,
    menu: null,
    wl: null,
    time: "day",
    motion: "lively",
    sources: { fixture: false, live: false },
    needsLeft: needsLeft({}),
    pins: [],
  };
  const listeners = new Set<() => void>();
  const set = (patch: Partial<ParkState>) => {
    state = { ...state, ...patch };
    for (const l of [...listeners]) l();
  };
  let cancelToast: (() => void) | null = null;
  let cancelLoader: (() => void) | null = null;
  const quiet = (p: Promise<unknown>) => p.catch(() => undefined);

  const dismissToast = () => {
    cancelToast?.();
    cancelToast = null;
    if (state.toast) set({ toast: null });
  };
  const toast = (message: string, actionLabel?: string, action?: () => void) => {
    cancelToast?.();
    cancelToast = schedule(() => {
      cancelToast = null;
      set({ toast: null });
    }, TOAST_MS);
    set({ toast: { message, actionLabel, action } });
  };
  const withDec = (key: DecisionKey, on: boolean): Dec => ({ ...state.dec, [key]: on });
  const undo = (key: DecisionKey) => {
    const dec = withDec(key, false);
    quiet(api.undo(key));
    cancelToast?.();
    cancelToast = null;
    set({ dec, needsLeft: needsLeft(dec), toast: null });
  };
  const go = (page: PageId, params?: Params) => {
    if (state.menu) set({ menu: null });
    navigate(parkPath(page, params));
  };
  const store: ParkStore = {
    getState: () => state,
    subscribe(l) {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    decide(key) {
      if (state.dec[key]) return;
      const dec = withDec(key, true);
      quiet(api.decide(key));
      set({ dec, needsLeft: needsLeft(dec) });
      const d = decisions.find((x) => x.k === key);
      toast(
        key === "depot" ? "Approved £3,420 for Laptop Depot" : "Supplier brief sent to 3 suppliers",
        "Undo",
        () => undo(key),
      );
      void d;
    },
    undo,
    addWorld(mode, query) {
      const w = makeWorld(mode, query, state.added.length + 1);
      set({ added: [w, ...state.added] });
      toast(`Started “${w.short}”`, "Open", () => {
        dismissToast();
        go("world", { id: w.id });
      });
      return w;
    },
    toast,
    dismissToast,
    setPref(key, value) {
      const prefs = { ...state.prefs, [key]: value };
      quiet(api.setPref(key, value));
      const m = prefs.motion;
      set({
        prefs,
        time: prefs.time === "night" ? "night" : "day",
        motion: m === "calm" || m === "still" || m === "lively" ? m : "lively",
      });
    },
    go,
    markRead() {
      if (!state.read) set({ read: true });
    },
    noteSource(source) {
      if (state.sources[source]) return;
      set({ sources: { ...state.sources, [source]: true } });
    },
    openWorld(id) {
      const w = worlds(state.dec, state.added).find((x) => x.id === id);
      if (!w) {
        go("world", { id });
        return;
      }
      cancelLoader?.();
      const ms = w.tier === "City" ? 340 : 250;
      set({ wl: { id, step: 0 }, menu: null });
      let step = 0;
      const tick = () => {
        step += 1;
        if (step < 3) set({ wl: { id, step } });
        else if (step === 3) {
          set({ wl: { id, step: 3 } });
          navigate(parkPath("world", { id }));
        } else {
          cancelLoader = null;
          set({ wl: null });
          return;
        }
        cancelLoader = schedule(tick, ms);
      };
      cancelLoader = schedule(tick, ms);
    },
    toggleMenu(which) {
      const menu = state.menu === which ? null : which;
      set({ menu, read: state.read || (which === "notif" && menu === "notif") });
    },
    closeMenu() {
      if (state.menu) set({ menu: null });
    },
    setPins(pins) {
      const same =
        pins.length === state.pins.length &&
        pins.every((p, i) => p.x === state.pins[i]?.x && p.y === state.pins[i]?.y);
      if (!same) set({ pins: pins.map((p) => ({ x: p.x, y: p.y })) });
    },
  };
  return store;
}
