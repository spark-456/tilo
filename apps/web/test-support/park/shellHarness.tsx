// WEB-3b test support: mounts the shell inside the real ParkProvider (fake Api, fake scheduler, injected
// navigate and viewport) and gives the tests the store, the app object and the wrapped Api the providers
// hand out. Nothing here is bundled. The engine mock (shellEngine.ts) is wired by each test file with
// vi.mock("../engines/park", ...) because vi.mock is hoisted per file.
import { type ReactElement, type ReactNode, act } from "react";
import { vi } from "vitest";
import { API_METHODS, type Api } from "../../src/park/api/index";
import type { AppCtx } from "../../src/park/app/AppCtx";
import { ParkProvider, useApp, useParkApi, useParkStore } from "../../src/park/app/context";
import type { ParkStore } from "../../src/park/app/store";
import { AppShell } from "../../src/park/shell/AppShell";
import { fakeApi, fakeScheduler } from "./appHarness";
import { mount } from "./componentsHarness";

export interface Seen {
  app: AppCtx;
  api: Api;
  store: ParkStore;
}
export const seen = {} as Seen;

/** Captures what a page would receive. Renders nothing. */
export function Probe(): null {
  seen.app = useApp();
  seen.api = useParkApi();
  seen.store = useParkStore();
  return null;
}

export interface ShellOpts {
  path?: string;
  api?: Api;
  viewport?: { vw: number; vh: number };
  /** QA-DEMO-1: mount as a demo session (recorded sample data), whatever Api is injected. */
  demo?: boolean;
}

/** The fixture Api with every result marked as read from a live service. */
export function liveApi(base: Api = fakeApi()): Api {
  const wrapped: Record<string, unknown> = {};
  for (const m of API_METHODS) {
    const fn = base[m] as (...a: never[]) => Promise<{ data: unknown; source: string }>;
    wrapped[m] = (...a: never[]) =>
      fn(...a).then((r) => ({ data: r.data, source: "live" as const }));
  }
  return wrapped as unknown as Api;
}

/** Lets resolved Api promises and the effects they cause run. */
export const settle = async (): Promise<void> => {
  await act(async () => undefined);
  await act(async () => undefined);
};

/** Mounts `ui` inside ParkProvider and a `[data-park]` root (ParkApp owns that root in the real app). */
export function mountShell(ui: ReactNode, o: ShellOpts = {}) {
  window.history.pushState({}, "", o.path ?? "/park/home");
  const api = o.api ?? fakeApi();
  const navigate = vi.fn();
  const sch = fakeScheduler();
  const tree = (viewport: { vw: number; vh: number }): ReactElement => (
    <ParkProvider
      api={api}
      navigate={navigate}
      schedule={sch.schedule}
      viewport={viewport}
      {...(o.demo !== undefined ? { demo: o.demo } : {})}
    >
      <div data-park="" data-time="day">
        <Probe />
        {ui}
      </div>
    </ParkProvider>
  );
  const m = mount(tree(o.viewport ?? { vw: 1440, vh: 900 }));
  /** The window was resized: same provider and store, new viewport. */
  const resize = (vw: number, vh: number) => m.render(tree({ vw, vh }));
  return { m, api, navigate, sch, resize };
}

/** The AppShell around a stand-in page, with the Api reads settled (notifications, user, sample flag). */
export async function mountApp(o: ShellOpts = {}) {
  const r = mountShell(
    <AppShell>
      <div data-testid="kid">page</div>
    </AppShell>,
    o,
  );
  await settle();
  return r;
}
