// WEB-11 test support: mounts `<ConnectorsPage app>` inside the WEB-3a `<ParkProvider api schedule viewport>`
// (the page takes only `{ app }` and reads data with useParkApi()), with the README AppCtx from appHarness
// `stubApp`, an Api spy wrapper and DOM queries (happy-dom; the repo has no @testing-library). Same pattern as
// teamHarness.ts. Lives here, not in the page folder, because park.static.test.ts reads page folder files as
// park code (which may import nothing from outside park). No timers: the scheduler is the injected fake.
import { type ReactElement, act } from "react";
import { type Mock, vi } from "vitest";
import { ClientProvider } from "../../src/api/ClientProvider";
import type { TiloClient } from "../../src/api/client";
import { createFixtureApi } from "../../src/park/api/fixtureApi";
import { API_METHODS, type Api, type ApiMethod } from "../../src/park/api/index";
import type { AppCtx } from "../../src/park/app/AppCtx";
import { ParkProvider } from "../../src/park/app/context";
import { ConnectorsPage } from "../../src/park/pages/Connectors/ConnectorsPage";
import { fakeScheduler, stubApp } from "./appHarness";
import { type Mounted, mount } from "./componentsHarness";

export type TestApp = AppCtx & {
  go: Mock<AppCtx["go"]>;
  decide: Mock<AppCtx["decide"]>;
  addWorld: Mock<AppCtx["addWorld"]>;
  toast: Mock<AppCtx["toast"]>;
  setPref: Mock<AppCtx["setPref"]>;
};

/** `stubApp("connectors", over)`: the README AppCtx on the connectors page, with spies on every action. */
export function makeApp(over: Partial<AppCtx> = {}): TestApp {
  return stubApp("connectors", over) as TestApp;
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

export interface Rendered extends Mounted {
  readonly api: Api;
}

/** The page inside `<ParkProvider api schedule viewport>` and the `data-park` root the shell gives it. */
export async function renderPage(
  app: AppCtx,
  api: Api = createFixtureApi(),
  time: "day" | "night" = "day",
  /** The app-level run client the page's run section reads. Default: the fixture client (sample run). A
   * deployed-mode test passes a non-fixture client so the section never shows the sample run. */
  client?: TiloClient,
): Promise<Rendered> {
  const sch = fakeScheduler();
  const page: ReactElement = (
    <ParkProvider api={api} schedule={sch.schedule} viewport={{ vw: app.vw, vh: app.vh }}>
      <div data-park="" data-time={time}>
        <ConnectorsPage app={app} />
      </div>
    </ParkProvider>
  );
  const tree = client ? <ClientProvider client={client}>{page}</ClientProvider> : page;
  const m = mount(tree);
  // The page loads its data on mount; let that settle inside act so no update lands outside it.
  await flush();
  return Object.assign(m, { api });
}

/** Polls (real timers, inside act) until `cond` holds; throws with `what` after about 2 s. */
export async function waitFor(cond: () => boolean, what: string): Promise<void> {
  for (let i = 0; i < 400; i++) {
    if (cond()) return;
    await act(async () => {
      await new Promise((r) => setTimeout(r, 5));
    });
  }
  throw new Error(`timed out waiting for: ${what}`);
}

/** Lets pending promise continuations run (no timers), inside act. */
export async function flush(ticks = 50): Promise<void> {
  await act(async () => {
    for (let i = 0; i < ticks; i++) await Promise.resolve();
  });
}

export const norm = (s: string | null | undefined): string => (s ?? "").replace(/\s+/g, " ").trim();
export const textOf = (el: Element): string => norm(el.textContent);

/** An element carrying `aria-label="<name>"` (the inventory's "labelled regions"). */
export const labelled = (root: ParentNode, name: string): HTMLElement | null =>
  root.querySelector<HTMLElement>(`[aria-label="${name}"]`);

export const buttonsIn = (root: ParentNode): HTMLButtonElement[] => [
  ...root.querySelectorAll<HTMLButtonElement>("button"),
];

/** First button whose text matches. */
export function buttonText(
  root: ParentNode,
  match: string | RegExp,
): HTMLButtonElement | undefined {
  return buttonsIn(root).find((b) =>
    typeof match === "string" ? textOf(b) === match : match.test(textOf(b)),
  );
}

/** True when some element's whole text is exactly `s` (copy is verbatim, not merged into other text). */
export function hasExactText(root: ParentNode, s: string): boolean {
  return [...root.querySelectorAll("*")].some((el) => textOf(el) === s);
}

export function countExactText(root: ParentNode, s: string): number {
  return [...root.querySelectorAll("*")].filter(
    (el) => textOf(el) === s && ![...el.children].some((c) => textOf(c) === s),
  ).length;
}

/** Types into a React-controlled input the way a browser does (value, then an input event). */
export function typeInto(input: HTMLInputElement, value: string): void {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  if (!set) throw new Error("no native value setter");
  act(() => {
    set.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

/** The tiles of the Connected region (each tile is one button) and the Add-a-tool rows' buttons. */
export const connectedTiles = (root: ParentNode): HTMLButtonElement[] => {
  const r = labelled(root, "Connected");
  return r ? buttonsIn(r) : [];
};
export const connectButtons = (root: ParentNode): HTMLButtonElement[] => {
  const r = labelled(root, "Available");
  return r ? buttonsIn(r) : [];
};
export const tileFor = (root: ParentNode, name: string): HTMLButtonElement | undefined =>
  connectedTiles(root).find((b) => textOf(b).includes(name));
