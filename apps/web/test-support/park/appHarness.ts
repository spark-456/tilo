// WEB-3a test support: fakes for the Park app skeleton (AppCtx, store, router, registry). Nothing here
// is bundled. The Api is the fixture Api with the four calls the store makes wrapped in spies; the
// scheduler is the injected `schedule(fn, ms)` that returns a cancel function (the pinned signature).
import { vi } from "vitest";
import { createFixtureApi } from "../../src/park/api/fixtureApi";
import type { Api } from "../../src/park/api/index";
import type { AppCtx, PageId } from "../../src/park/app/AppCtx";

export const PAGE_LABEL: Record<PageId, string> = {
  home: "Home",
  worlds: "Worlds",
  world: "World",
  skills: "Skills",
  ledger: "Ledger",
  agenda: "Agenda",
  team: "Team",
  profile: "Profile",
  more: "More",
  connectors: "Connectors",
};

export type SpyApi = Api & {
  decide: ReturnType<typeof vi.fn>;
  undo: ReturnType<typeof vi.fn>;
  startWorld: ReturnType<typeof vi.fn>;
  setPref: ReturnType<typeof vi.fn>;
};

/** The fixture Api (source "fixture") with decide, undo, startWorld and setPref spied on. */
export function fakeApi(): SpyApi {
  const base = createFixtureApi();
  return {
    ...base,
    decide: vi.fn(base.decide),
    undo: vi.fn(base.undo),
    startWorld: vi.fn(base.startWorld),
    setPref: vi.fn(base.setPref),
  } as SpyApi;
}

export interface FakeTimer {
  readonly fn: () => void;
  readonly ms: number;
  cancelled: boolean;
  fired: boolean;
}

/** `schedule(fn, ms)` returns a cancel function. Nothing runs by itself: a test calls `fire`. */
export function fakeScheduler() {
  const timers: FakeTimer[] = [];
  const schedule = vi.fn((fn: () => void, ms: number): (() => void) => {
    const t: FakeTimer = { fn, ms, cancelled: false, fired: false };
    timers.push(t);
    return () => {
      t.cancelled = true;
    };
  });
  return {
    schedule,
    timers,
    /** Timers that are neither cancelled nor fired. */
    live: (): FakeTimer[] => timers.filter((t) => !t.cancelled && !t.fired),
    /** Runs a timer the way the clock would: never after it was cancelled. */
    fire(t: FakeTimer | undefined): void {
      if (!t || t.cancelled || t.fired) return;
      t.fired = true;
      t.fn();
    },
  };
}

export function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const v of Object.values(value as Record<string, unknown>)) deepFreeze(v);
  }
  return value;
}

/** A complete AppCtx for components that only need to be handed one. */
export function stubApp(page: PageId = "home", overrides: Partial<AppCtx> = {}): AppCtx {
  return {
    page,
    params: {},
    go: vi.fn(),
    dec: {},
    decide: vi.fn(),
    needsLeft: 2,
    added: [],
    addWorld: vi.fn(),
    toast: vi.fn(),
    time: "day",
    night: false,
    motion: "lively",
    setPref: vi.fn(),
    prefs: {},
    vw: 1440,
    vh: 900,
    pins: [],
    ready: true,
    ...overrides,
  } as AppCtx;
}
