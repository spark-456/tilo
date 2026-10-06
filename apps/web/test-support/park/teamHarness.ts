// WEB-10 test support: mounts `<TeamPage app>` inside the WEB-3a `<ParkProvider api>` (the page takes only
// `{ app }` and reads data with useParkApi()), with the README AppCtx from appHarness `stubApp`, and a spy
// wrapper over every Api method. Lives here, not in the page folder, because park.static.test.ts reads page
// folder files as park code (which may import nothing from outside park). Query/action helpers are in
// src/park/pages/Team/testApp.ts. No timers: the scheduler is the injected fake; async work is flushed with
// microtasks.
import { type ReactElement, createElement } from "react";
import { type Mock, vi } from "vitest";
import { createFixtureApi } from "../../src/park/api/fixtureApi";
import { API_METHODS, type Api, type ApiMethod } from "../../src/park/api/index";
import type { AppCtx } from "../../src/park/app/AppCtx";
import { ParkProvider } from "../../src/park/app/context";
import { TeamPage } from "../../src/park/pages/Team/TeamPage";
import { settle } from "../../src/park/pages/Team/testApp";
import { fakeScheduler, stubApp } from "./appHarness";
import { type Mounted, cleanup, mount } from "./componentsHarness";

export { cleanup };

export type TestApp = AppCtx & {
  go: Mock<AppCtx["go"]>;
  decide: Mock<AppCtx["decide"]>;
  addWorld: Mock<AppCtx["addWorld"]>;
  toast: Mock<AppCtx["toast"]>;
  setPref: Mock<AppCtx["setPref"]>;
};

/** `stubApp("team", over)`: README AppCtx on the team page, day, with go/decide/toast/addWorld/setPref spies. */
export function makeApp(over: Partial<AppCtx> = {}): TestApp {
  return stubApp("team", over) as TestApp;
}

export type SpyApi = Api & { [M in ApiMethod]: Mock };

/** The fixture Api with every method wrapped in a spy (results unchanged: `source: "fixture"`). */
export function spyApi(base: Api = createFixtureApi()): SpyApi {
  const entries = API_METHODS.map((m) => [
    m,
    vi.fn((...a: never[]) => (base[m] as (...args: unknown[]) => unknown)(...a)),
  ]);
  return Object.fromEntries(entries) as unknown as SpyApi;
}

export interface Rendered {
  readonly m: Mounted;
  readonly root: HTMLElement;
  /** The page for another `app` inside the same provider (for `m.render`, to change the route params). */
  tree(app: AppCtx): ReactElement;
}

/** Mount the page (the fixture Api unless `api` is given, e.g. `createLiveApi()`) and wait for its data. */
export async function renderTeam(app: AppCtx, api: Api = createFixtureApi()): Promise<Rendered> {
  const sch = fakeScheduler();
  const tree = (a: AppCtx): ReactElement =>
    createElement(
      ParkProvider,
      { api, schedule: sch.schedule, viewport: { vw: a.vw, vh: a.vh } },
      createElement(TeamPage, { app: a }),
    );
  const m = mount(tree(app));
  await settle();
  return { m, root: m.container, tree };
}
