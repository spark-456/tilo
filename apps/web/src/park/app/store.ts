import { needsLeft as countNeedsLeft, makeWorld } from "../api/fixtures/worlds";
// The shell store (README "State and data"; the prototype class in `Tilo App.dc.html`: decide, undo,
// addWorld, toast, go, needsLeft). Framework-free: React reads it through useSyncExternalStore in
// context.tsx. State is replaced on every change, never mutated. The one timer is the toast's, and it
// is injected as `schedule` so a test never waits.
import type { Api } from "../api/index";
import type { Dec, DecisionKey, Source, TierKey, World } from "../api/types";
import { TOAST_MS } from "../components/Toast";
import type { Motion, PageId, Params } from "./AppCtx";
import { parkPath } from "./router";

/** Runs `fn` after `ms` and returns the function that cancels it. */
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

/** The world-opening overlay of the prototype; WEB-3b sets it. */
export interface WorldLaunch {
  id: string;
  step: number;
}

export interface ParkState {
  dec: Dec;
  added: World[];
  prefs: Record<string, unknown>;
  toast: ToastState | null;
  read: boolean;
  menu: "notif" | "acct" | null;
  wl: WorldLaunch | null;
  time: "day" | "night";
  motion: Motion;
  sources: { fixture: boolean; live: boolean };
  needsLeft: number;
}

export interface ParkStore {
  getState(): ParkState;
  subscribe(listener: () => void): () => void;
  decide(key: DecisionKey): void;
  undo(key: DecisionKey): void;
  addWorld(mode: TierKey, query: string): World;
  toast(message: string, actionLabel?: string, action?: () => void): void;
  dismissToast(): void;
  setPref(key: string, value: unknown): void;
  go(page: PageId, params?: Params): void;
  markRead(): void;
  noteSource(source: Source): void;
}

export interface ParkStoreDeps {
  api: Api;
  navigate: (to: string) => void;
  schedule: Schedule;
  now?: () => number;
}

const MOTIONS: readonly Motion[] = ["lively", "calm", "still"];

const derive = (prefs: Record<string, unknown>, dec: Dec) => ({
  time: prefs.time === "night" ? ("night" as const) : ("day" as const),
  motion: MOTIONS.find((m) => m === prefs.motion) ?? "lively",
  needsLeft: countNeedsLeft(dec),
});

const DECIDED: Record<DecisionKey, string> = {
  depot: "Approved £3,420 for Laptop Depot",
  mail: "Supplier brief sent to 3 suppliers",
};

export function createParkStore({ api, navigate, schedule }: ParkStoreDeps): ParkStore {
  let state: ParkState = {
    dec: {},
    added: [],
    prefs: {},
    toast: null,
    read: false,
    menu: null,
    wl: null,
    sources: { fixture: false, live: false },
    ...derive({}, {}),
  };
  const listeners = new Set<() => void>();
  let cancelToast: (() => void) | null = null;

  const set = (next: ParkState): void => {
    state = next;
    for (const l of [...listeners]) l();
  };
  // A call to the api is best effort here: the screen state is the source of truth until the live
  // endpoints exist, and a rejection must never reach the page.
  const quiet = (call: Promise<unknown>): void => {
    call.catch(() => undefined);
  };

  const clearTimer = (): void => {
    cancelToast?.();
    cancelToast = null;
  };
  const dismissToast = (): void => {
    clearTimer();
    if (state.toast !== null) set({ ...state, toast: null });
  };
  // Starts the one toast timer and returns the toast to put in the state.
  const arm = (message: string, actionLabel?: string, action?: () => void): ToastState => {
    clearTimer();
    cancelToast = schedule(dismissToast, TOAST_MS);
    return { message, actionLabel, action };
  };
  const toast = (message: string, actionLabel?: string, action?: () => void): void =>
    set({ ...state, toast: arm(message, actionLabel, action) });

  const update = (patch: Partial<Pick<ParkState, "dec" | "added" | "prefs" | "toast">>): void => {
    const merged = { ...state, ...patch };
    set({ ...merged, ...derive(merged.prefs, merged.dec) });
  };

  const undo = (key: DecisionKey): void => {
    quiet(api.undo(key));
    clearTimer();
    update({ dec: { ...state.dec, [key]: false }, toast: null });
  };

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    decide(key) {
      if (state.dec[key]) return;
      quiet(api.decide(key));
      update({
        dec: { ...state.dec, [key]: true },
        toast: arm(DECIDED[key], "Undo", () => undo(key)),
      });
    },
    undo,
    addWorld(mode, query) {
      const world = makeWorld(mode, query, state.added.length + 1);
      quiet(api.startWorld(mode, query));
      const open = () => {
        dismissToast();
        navigate(parkPath("world", { id: world.id }));
      };
      update({
        added: [world, ...state.added],
        toast: arm(`Started “${world.short}”`, "Open", open),
      });
      return world;
    },
    toast,
    dismissToast,
    setPref(key, value) {
      quiet(api.setPref(key, value));
      update({ prefs: { ...state.prefs, [key]: value } });
    },
    go: (page, params) => navigate(parkPath(page, params)),
    markRead() {
      if (!state.read) set({ ...state, read: true });
    },
    noteSource(source) {
      if (state.sources[source]) return;
      set({ ...state, sources: { ...state.sources, [source]: true } });
    },
  };
}
