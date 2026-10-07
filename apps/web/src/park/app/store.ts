// The shell store (README "State and data"; the prototype class in `Tilo App.dc.html`: decide, undo,
// addWorld, toast, go, needsLeft). Framework-free: React reads it through useSyncExternalStore in
// context.tsx. State is replaced on every change, never mutated. The one timer is the toast's, and it
// is injected as `schedule` so a test never waits.
import { TiloApiError } from "../../api/http";
import { needsLeft as countNeedsLeft, makeWorld, worlds } from "../api/fixtures/worlds";
import type { Api } from "../api/index";
import type { Dec, Decision, DecisionKey, Source, TierKey, World } from "../api/types";
import { TOAST_MS } from "../components/Toast";
import type { Motion, PageId, Params } from "./AppCtx";
import { parkPath } from "./router";

/** A live answer that failed in a way the Api did not describe. */
const NOT_RECORDED = "Tilo could not record that answer. Nothing was sent.";

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

/** The world-opening overlay of the prototype: the world and the step the loader has reached (0 to 3). */
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
  /** The loader first (README "Open a world"), the page at its third step. An unknown id just goes. */
  openWorld(id: string): void;
  /** Opens the menu, or closes it when it is the one open. Opening the notifications reads them. */
  toggleMenu(menu: "notif" | "acct"): void;
  closeMenu(): void;
  markRead(): void;
  noteSource(source: Source): void;
  /** The decisions the Api returned (their toast copy). Until they arrive, a toast says a plain line. */
  setDecisions(list: readonly Decision[]): void;
  /** Cancels every timer the store holds (the toast's and the loader's). */
  dispose(): void;
}

export interface ParkStoreDeps {
  api: Api;
  navigate: (to: string) => void;
  schedule: Schedule;
  now?: () => number;
}

/** Milliseconds per loader step: cities take longer to wake (README "Open a world"). */
const STEP_MS = { City: 340, other: 250 } as const;
const MOTIONS: readonly Motion[] = ["lively", "calm", "still"];

const derive = (prefs: Record<string, unknown>, dec: Dec) => ({
  time: prefs.time === "night" ? ("night" as const) : ("day" as const),
  motion: MOTIONS.find((m) => m === prefs.motion) ?? "lively",
  needsLeft: countNeedsLeft(dec),
});

/** What the toast says when an item is decided: the designed copy of the Api's decision, else a plain line
 * built from the item's own fields (the Api may not have it: live mode before the endpoint exists). */
function decidedText(decision: Decision | undefined): string {
  if (!decision) return "Decision recorded";
  return decision.toast || (decision.done ? `${decision.title}: ${decision.done}` : decision.title);
}

/** A live answer says what was recorded, never that the work is done: the outbox still has to act (HR-1). */
function answeredText(decision: Decision | undefined): string {
  return decision ? `${decision.yes} recorded: ${decision.title}` : "Answer recorded";
}

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
  // The decisions with their designed copy, handed over by the shell once the Api has returned them.
  let decisions: readonly Decision[] = [];
  // Live answers in flight: a second tap sends nothing until the first one is settled.
  const pending = new Set<DecisionKey>();
  let cancelToast: (() => void) | null = null;
  let cancelLoader: (() => void) | null = null;

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

  const stopLoader = (): void => {
    cancelLoader?.();
    cancelLoader = null;
  };

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
      if (state.dec[key] || pending.has(key)) return;
      if (state.sources.live) {
        // Live (WIRE-3): a decision is taken only when tilo-api recorded the answer (HR-1). No Undo: no route
        // reopens a card. A failure leaves the card open and says why; another world's card offers to open it.
        pending.add(key);
        api.decide(key).then(
          () => {
            pending.delete(key);
            update({
              dec: { ...state.dec, [key]: true },
              toast: arm(answeredText(decisions.find((d) => d.k === key))),
            });
          },
          (e: unknown) => {
            pending.delete(key);
            const said = e instanceof TiloApiError ? e.message : NOT_RECORDED;
            const world = decisions.find((d) => d.k === key)?.world;
            if (e instanceof TiloApiError && e.code === "open_in_world" && world) {
              toast(said, "Open in world", () => {
                dismissToast();
                navigate(parkPath("world", { id: world }));
              });
            } else toast(said);
          },
        );
        return;
      }
      quiet(api.decide(key));
      update({
        dec: { ...state.dec, [key]: true },
        toast: arm(decidedText(decisions.find((d) => d.k === key)), "Undo", () => undo(key)),
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
    go(page, params) {
      if (state.menu !== null) set({ ...state, menu: null });
      navigate(parkPath(page, params));
    },
    openWorld(id) {
      stopLoader();
      const world = worlds(state.dec, state.added).find((w) => w.id === id);
      if (!world) {
        set({ ...state, wl: null, menu: null });
        navigate(parkPath("world", { id }));
        return;
      }
      const ms = world.tier === "City" ? STEP_MS.City : STEP_MS.other;
      // One timer at a time: each tick sets the step and arms the next. Step 3 swaps the page under the
      // card; the fourth tick removes the card.
      const arm = (next: number): void => {
        cancelLoader = schedule(() => run(next), ms);
      };
      const run = (step: number): void => {
        if (step > 3) {
          cancelLoader = null;
          set({ ...state, wl: null });
          return;
        }
        set({ ...state, wl: { id, step } });
        if (step === 3) navigate(parkPath("world", { id }));
        arm(step + 1);
      };
      set({ ...state, wl: { id, step: 0 }, menu: null });
      arm(1);
    },
    toggleMenu(menu) {
      set({
        ...state,
        menu: state.menu === menu ? null : menu,
        read: menu === "notif" ? true : state.read,
      });
    },
    closeMenu() {
      if (state.menu !== null) set({ ...state, menu: null });
    },
    markRead() {
      if (!state.read) set({ ...state, read: true });
    },
    noteSource(source) {
      if (state.sources[source]) return;
      set({ ...state, sources: { ...state.sources, [source]: true } });
    },
    setDecisions(list) {
      decisions = list;
    },
    dispose() {
      stopLoader();
      clearTimer();
    },
  };
}
