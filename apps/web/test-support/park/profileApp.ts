// WEB-12 test support: the AppCtx every Profile test hands the page. It is stubApp (WEB-3a appHarness: a
// complete README AppCtx, page "profile", day, nothing decided) with the five effect functions typed as
// spies. It lives here, not in pages/Profile/testApp.ts, because park.static.test.ts reads the page folder
// as park code and park code imports nothing from test-support.
import type { Mock } from "vitest";
import type { AppCtx } from "../../src/park/app/AppCtx";
import { stubApp } from "./appHarness";

export type TestApp = AppCtx & {
  go: Mock<AppCtx["go"]>;
  decide: Mock<AppCtx["decide"]>;
  addWorld: Mock<AppCtx["addWorld"]>;
  toast: Mock<AppCtx["toast"]>;
  setPref: Mock<AppCtx["setPref"]>;
};

/** README AppCtx, page "profile", day, motion "lively"; go/decide/toast/addWorld/setPref are spies. */
export function makeApp(over: Partial<AppCtx> = {}): TestApp {
  return stubApp("profile", over) as TestApp;
}
