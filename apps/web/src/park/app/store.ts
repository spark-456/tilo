// The shell store (README "State and data"; the prototype class in `Tilo App.dc.html`: decide, undo,
// addWorld, toast, go, needsLeft). Framework-free: React reads it through useSyncExternalStore in
// context.tsx. State is replaced on every change, never mutated. The one timer is the toast's, and it
// is injected as `schedule` so a test never waits.
import { TiloApiError, isLifetimeCap } from "../../api/http";
import { buildHandoffDecisions } from "../api/fixtures/buildHandoff";
import { needsLeft as countNeedsLeft, makeWorld, worlds } from "../api/fixtures/worlds";
import { type Api, askQuick, startWithFiles } from "../api/index";
import { NotBuilt } from "../api/liveApi";
import { type OneStepApi, type RunPlan, oneStepOf } from "../api/oneStep";
import type {
  Dec,
  Decision,
  DecisionKey,
  QuickCost,
  Source,
  SwitchReason,
  TierKey,
  World,
} from "../api/types";
import { TOAST_MS } from "../components/Toast";
import type { Motion, PageId, Params } from "./AppCtx";
import { parkPath } from "./router";
import { openServedCount } from "./servedDecisions";

/** One step of the one-step start: its value, or the plain reason it stopped (`capped`: the lifetime-cap pop-up says it). */
export type RunStep<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly message: string; readonly capped: boolean };

/** A live answer that failed in a way the Api did not describe. */
const NOT_RECORDED = "Tilo could not record that answer. Nothing was sent.";
/** What a start that failed says when the Api did not describe it, or the API is not connected (FR-UX-13). */
const NOT_STARTED = "Tilo could not start that task. Try again.";
const NOT_CONNECTED = "Starting work is not connected yet.";
/** QA-DEMO-1 (HR-1): a demo session replays recorded data, so an approval there records nothing and says so. */
export const DEMO_DECIDE = "Sample data: nothing was approved. Sign in to approve real decisions.";
/** QA-DEMO-1: a demo session starts no run; the composer says so instead of inventing progress. */
export const DEMO_START = "Demo sessions replay a recorded run; sign in to start your own.";

/** What a Quick ask came to: an answer (`sample` when the Api is the fixture), an offer to switch, or a plain failure. */
export type QuickOutcome =
  | { kind: "answered"; text: string; cost: QuickCost | null; sample: boolean }
  | { kind: "switch"; reason: SwitchReason }
  | { kind: "error"; message: string };

/** One honest sentence per refusal of a Quick ask (the typed text stays on the page). */
export function quickErrorMessage(e: unknown): string {
  if (e instanceof NotBuilt) return "Quick answers are not connected yet.";
  if (!(e instanceof TiloApiError)) return "Tilo could not answer that. Try again.";
  if (e.status === 429) {
    return "Quick answers are limited right now (today’s allowance or too many asks). Try again later.";
  }
  if (e.status === 403 && (e.code === "spend_cap_reached" || e.message === "spend_cap_reached")) {
    // SEAM (CL-REACH lifetime-cap pop-up): the pop-up replaces this sentence when it lands.
    return "The spending limit for this account has been reached, so nothing new can run.";
  }
  if (e.status === 503) {
    return e.replayOnly
      ? "Live models are unavailable right now, so Tilo could not answer. Try again later."
      : e.message;
  }
  if (e.status !== null && e.status >= 500) return "Tilo had a problem on its side. Try again.";
  return e.message;
}

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
  /** SEC-16: a start was refused at the lifetime allowance: the shell shows the pop-up (no toast, no world). */
  lifetimeCap: boolean;
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
  /** The fixture path: adds the world at once and returns it. */
  addWorld(mode: TierKey, query: string): World;
  /** The live path (FR-UX-13): the Api is asked first and the promise settles with whether the server accepted
   * the task; a world is added, and Open offered, only then (HR-1). The shell picks one of the two (`useApp`). */
  startWorld(mode: TierKey, query: string, files?: readonly File[]): Promise<boolean>;
  /**
   * Quick (COST-FAST-1): one direct question. It makes no world, adds nothing, toasts nothing and never animates;
   * the page shows the outcome. `mode` is only the size on screen. A second call while one is in flight shares it.
   */
  askQuick(mode: TierKey, query: string): Promise<QuickOutcome>;
  /**
   * SIMPLE-RUN-1: the one-step start (live only; false on a fixture Api). `prepareRun` makes the intake, skips every
   * question and prices the recommended approach; `startRun` is the person's Start, the approval of that plan's cap.
   */
  readonly oneStep: boolean;
  prepareRun(text: string, files?: readonly File[]): Promise<RunStep<RunPlan>>;
  reviseRun(plan: RunPlan, field: string, answer: string): Promise<RunStep<RunPlan>>;
  startRun(plan: RunPlan): Promise<RunStep<string>>;
  toast(message: string, actionLabel?: string, action?: () => void): void;
  dismissToast(): void;
  dismissLifetimeCap(): void;
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
  /** QA-DEMO-1: a demo session (sample company): a decision is explained, never recorded or shown as done. */
  demo?: boolean;
}

/** Milliseconds per loader step: cities take longer to wake (README "Open a world"). */
const STEP_MS = { City: 340, other: 250 } as const;
const MOTIONS: readonly Motion[] = ["lively", "calm", "still"];
const TIME_STORAGE_KEY = "tilo.time";
const MOTION_STORAGE_KEY = "tilo.motion";
const THEME_STORAGE_KEY = "tilo.theme";
const STORED_PREFS = new Map([
  ["time", TIME_STORAGE_KEY],
  ["motion", MOTION_STORAGE_KEY],
  ["theme", THEME_STORAGE_KEY],
]);

function readStoredPrefs(): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  try {
    const t = window.localStorage.getItem(TIME_STORAGE_KEY);
    if (t === "day" || t === "night") out.time = t;
    const m = window.localStorage.getItem(MOTION_STORAGE_KEY);
    if (m === "lively" || m === "calm" || m === "still") out.motion = m;
    const th = window.localStorage.getItem(THEME_STORAGE_KEY); // FR-WLD-15: validated by themeFor where it is used
    if (th !== null && /^[a-z][a-z0-9-]{0,31}$/.test(th)) out.theme = th;
  } catch {
    // storage absent (Node tests) or blocked (private mode)
  }
  return out;
}

function writeStoredPref(key: string, value: unknown): void {
  const storageKey = STORED_PREFS.get(key);
  if (storageKey === undefined) return;
  try {
    window.localStorage.setItem(storageKey, String(value));
  } catch {
    // storage absent or blocked: preference still applies for this session
  }
}

const derive = (prefs: Record<string, unknown>, dec: Dec) => ({
  time: prefs.time === "night" ? ("night" as const) : ("day" as const),
  motion: MOTIONS.find((m) => m === prefs.motion) ?? "calm",
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

export function createParkStore({ api, navigate, schedule, demo }: ParkStoreDeps): ParkStore {
  const initialPrefs = readStoredPrefs();
  let state: ParkState = {
    dec: {},
    added: [],
    prefs: initialPrefs,
    toast: null,
    read: false,
    menu: null,
    wl: null,
    lifetimeCap: false,
    sources: { fixture: false, live: false },
    ...derive(initialPrefs, {}),
  };
  const listeners = new Set<() => void>();
  // The decisions with their designed copy, handed over by the shell once the Api has returned them.
  let decisions: readonly Decision[] = [];
  // Live answers in flight: a second tap sends nothing until the first one is settled.
  const pending = new Set<DecisionKey>();
  // The live start in flight: a second call gets the same answer and sends nothing.
  let starting: Promise<boolean> | null = null;
  let asking: Promise<QuickOutcome> | null = null;
  let cancelToast: (() => void) | null = null;
  let cancelLoader: (() => void) | null = null;

  const set = (next: ParkState): void => {
    state = next;
    for (const l of [...listeners]) l();
  };
  // One call of the one-step start; a refusal becomes its plain reason, and one in flight is never doubled.
  let stepping = false;
  const runStep = async <T>(call: (one: OneStepApi) => Promise<T>): Promise<RunStep<T>> => {
    const one = oneStepOf(api);
    if (one === null) return { ok: false, message: NOT_CONNECTED, capped: false };
    if (stepping)
      return { ok: false, message: "Tilo is still working on the last step.", capped: false };
    stepping = true;
    try {
      return { ok: true, value: await call(one) };
    } catch (e) {
      if (isLifetimeCap(e)) {
        set({ ...state, lifetimeCap: true });
        return { ok: false, message: "", capped: true };
      }
      return {
        ok: false,
        message: e instanceof TiloApiError ? e.message : NOT_STARTED,
        capped: false,
      };
    } finally {
      stepping = false;
    }
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

  // On the live path the count is the served decisions still open (BQ-UX11-1); the fixture path keeps the sample count.
  const needsFor = (s: ParkState): number =>
    s.sources.live ? openServedCount(decisions, s.dec) : countNeedsLeft(s.dec);

  const update = (patch: Partial<Pick<ParkState, "dec" | "added" | "prefs" | "toast">>): void => {
    const merged = { ...state, ...patch };
    set({ ...merged, ...derive(merged.prefs, merged.dec), needsLeft: needsFor(merged) });
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
      if (demo === true) {
        toast(DEMO_DECIDE);
        return;
      }
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
        toast: arm(
          decidedText(
            decisions.find((d) => d.k === key) ?? buildHandoffDecisions.find((d) => d.k === key),
          ),
          "Undo",
          () => undo(key),
        ),
      });
    },
    undo,
    startWorld(mode, query, files) {
      // Live (FR-UX-13): the intake call is made first; the world is added, and Open offered, only after the
      // server accepted the task. The task is not approved yet, so Open goes to its understanding screen and
      // nothing says it is running (HR-1). A failure adds nothing and says why.
      if (starting) return starting;
      starting = (
        files?.length ? startWithFiles(api, mode, query, files) : api.startWorld(mode, query)
      ).then(
        ({ data }) => {
          starting = null;
          const { world } = data;
          update({
            added: [world, ...state.added],
            // The old Understanding screen is retired (SIMPLE-RUN-1): nothing offers it. Home's one-step flow is the
            // live start; this path only answers an Api that has no `oneStep`.
            toast: arm(`“${world.short}” was sent to Tilo.`),
          });
          return true;
        },
        (e: unknown) => {
          starting = null;
          if (isLifetimeCap(e)) {
            set({ ...state, lifetimeCap: true }); // the pop-up says it; no toast with the server's words, nothing added
            return false;
          }
          toast(
            e instanceof TiloApiError
              ? e.message
              : e instanceof NotBuilt
                ? NOT_CONNECTED
                : NOT_STARTED,
          );
          return false;
        },
      );
      return starting;
    },
    oneStep: oneStepOf(api) !== null,
    prepareRun: (text, files) => runStep((one) => one.prepare(text, files ?? [])),
    reviseRun: (plan, field, answer) => runStep((one) => one.revise(plan.taskId, field, answer)),
    startRun: (plan) => runStep((one) => one.start(plan)),
    askQuick(mode, query) {
      if (asking) return asking;
      asking = askQuick(api, mode, query).then(
        ({ data, source }): QuickOutcome => {
          asking = null;
          return data.kind === "answered"
            ? { kind: "answered", text: data.text, cost: data.cost, sample: source !== "live" }
            : { kind: "switch", reason: data.reason };
        },
        (e: unknown): QuickOutcome => {
          asking = null;
          return { kind: "error", message: quickErrorMessage(e) };
        },
      );
      return asking;
    },
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
    dismissLifetimeCap() {
      if (state.lifetimeCap) set({ ...state, lifetimeCap: false });
    },
    setPref(key, value) {
      writeStoredPref(key, value);
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
      const next = { ...state, sources: { ...state.sources, [source]: true } };
      set({ ...next, needsLeft: needsFor(next) });
    },
    setDecisions(list) {
      decisions = list;
      if (state.sources.live) set({ ...state, needsLeft: needsFor(state) });
    },
    dispose() {
      stopLoader();
      clearTimer();
    },
  };
}
