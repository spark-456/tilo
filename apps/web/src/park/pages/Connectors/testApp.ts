// WEB-11 test helper: a full AppCtx built from the handoff README contract ("The `app` prop"), with
// vi.fn() for go, decide, toast, addWorld and setPref. Page tests read the calls, never window.location.
// AppCtx arrives with WEB-3a (park/app/AppCtx.ts, not pushed when this was written). The shape follows
// the README field list exactly: page, params, go, dec, decide, needsLeft, added, addWorld, toast,
// time, night, motion, setPref, prefs, vw, vh, pins, ready. Defaults are the quiet ones: day, motion
// "still" (nothing animates), no decision taken, 1440x900.
import { type Mock, vi } from "vitest";
import { makeWorld } from "../../api/fixtures";
import type { TierKey } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";

export type TestApp = AppCtx & {
  go: Mock<AppCtx["go"]>;
  decide: Mock<AppCtx["decide"]>;
  toast: Mock<AppCtx["toast"]>;
  addWorld: Mock<AppCtx["addWorld"]>;
  setPref: Mock<AppCtx["setPref"]>;
};

export function testApp(over: Partial<AppCtx> = {}): TestApp {
  const base: AppCtx = {
    page: "connectors",
    params: {},
    go: vi.fn<AppCtx["go"]>(),
    dec: {},
    decide: vi.fn<AppCtx["decide"]>(),
    needsLeft: 2,
    added: [],
    addWorld: vi.fn<AppCtx["addWorld"]>((mode: TierKey, query: string) =>
      makeWorld(mode, query, 1),
    ),
    toast: vi.fn<AppCtx["toast"]>(),
    time: "day",
    night: false,
    motion: "still",
    setPref: vi.fn<AppCtx["setPref"]>(),
    prefs: {},
    vw: 1440,
    vh: 900,
    pins: [
      { x: 320, y: 410 },
      { x: 760, y: 300 },
      { x: 1100, y: 520 },
    ],
    ready: true,
  };
  return { ...base, ...over } as TestApp;
}
