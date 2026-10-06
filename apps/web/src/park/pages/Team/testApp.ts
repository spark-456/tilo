// WEB-10 test helper (not a test): a full AppCtx built from the handoff README contract, a spying Api, the
// mount/settle/query helpers the Team tests share. AppCtx arrives in WEB-3a (park/app/AppCtx.ts), so every
// test file that imports this one fails until that branch is merged, which is the intended order.
// The repo has no @testing-library, so this mounts with react-dom in happy-dom. It lives in the page folder
// and park.static.test.ts reads it as park code: it imports nothing from outside park, so the mount helper
// is a local copy of test-support/park/componentsHarness. No timers: async work is flushed with microtasks.
import { type ReactElement, act, createElement } from "react";
import { type Root, createRoot } from "react-dom/client";
import { type Mock, vi } from "vitest";
import { API_METHODS, type Api, type ApiMethod } from "../../api";
import { createFixtureApi } from "../../api/fixtureApi";
import { makeWorld } from "../../api/fixtures";
import type { AppCtx } from "../../app/AppCtx";
import { TeamPage } from "./TeamPage";

Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);

export interface Mounted {
  readonly container: HTMLElement;
  render(ui: ReactElement): void;
  unmount(): void;
}
const live: Mounted[] = [];

function mount(ui: ReactElement): Mounted {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  let open = true;
  const m: Mounted = {
    container,
    render(next) {
      act(() => root.render(next));
    },
    unmount() {
      if (!open) return;
      open = false;
      act(() => root.unmount());
      container.remove();
    },
  };
  m.render(ui);
  live.push(m);
  return m;
}

/** Call from afterEach in every test file that renders the page. */
export function cleanup(): void {
  for (const m of live.splice(0)) m.unmount();
  document.body.replaceChildren();
}

export type TestApp = AppCtx & {
  go: Mock<AppCtx["go"]>;
  decide: Mock<AppCtx["decide"]>;
  addWorld: Mock<AppCtx["addWorld"]>;
  toast: Mock<AppCtx["toast"]>;
  setPref: Mock<AppCtx["setPref"]>;
};

/** README AppCtx, page "team", day, nothing decided yet; go/decide/toast/addWorld/setPref are spies. */
export function makeApp(over: Partial<AppCtx> = {}): TestApp {
  const base: AppCtx = {
    page: "team",
    params: {},
    go: vi.fn<AppCtx["go"]>(),
    dec: { depot: false, mail: false },
    decide: vi.fn<AppCtx["decide"]>(),
    needsLeft: 2,
    added: [],
    addWorld: vi.fn<AppCtx["addWorld"]>(() => makeWorld("quick", "Test job", 1)),
    toast: vi.fn<AppCtx["toast"]>(),
    time: "day",
    night: false,
    motion: "lively",
    setPref: vi.fn<AppCtx["setPref"]>(),
    prefs: {},
    vw: 1440,
    vh: 900,
    pins: [],
    ready: true,
  };
  return { ...base, ...over } as TestApp;
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

/** Let promises, effects and the state updates they cause finish (microtasks only). */
export async function settle(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 30; i++) await Promise.resolve();
  });
}

export interface Rendered {
  readonly m: Mounted;
  readonly root: HTMLElement;
}

/** Mount `<TeamPage app={app} />` (the fixture Api by default) and wait for its data. */
export async function renderTeam(app: AppCtx, api?: Api): Promise<Rendered> {
  const m = mount(createElement(TeamPage, { app, ...(api ? { api } : {}) }));
  await settle();
  return { m, root: m.container };
}

// ---- queries (no accessibility tree in happy-dom: roles and names are read from the attributes) ----

export const region = (root: ParentNode, name: string): HTMLElement => {
  const el = root.querySelector<HTMLElement>(`[aria-label="${name}"]`);
  if (!el) throw new Error(`no region named "${name}"`);
  return el;
};

/** Table rows: a real <tr>, or a div with role="row" (biome flags that spelling, a <tr> with display:grid is fine). */
export const rowsOf = (root: ParentNode): HTMLElement[] => [
  ...root.querySelectorAll<HTMLElement>('tr, [role="row"]'),
];

/** The element's own text (its direct text nodes), trimmed: how a visible string is read. */
export const ownText = (el: Element): string =>
  [...el.childNodes]
    .filter((n) => n.nodeType === 3)
    .map((n) => n.textContent ?? "")
    .join("")
    .trim();

/** Every visible string under `root` (own text of every element), as a set. Options count: they are copy. */
export function strings(root: ParentNode): Set<string> {
  const out = new Set<string>();
  for (const el of root.querySelectorAll("*")) {
    if (el.tagName === "STYLE" || el.tagName === "SCRIPT") continue;
    const t = ownText(el);
    if (t) out.add(t);
  }
  return out;
}

export const buttonNamed = (root: ParentNode, name: string): HTMLButtonElement => {
  const hit = [...root.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => (b.getAttribute("aria-label") ?? b.textContent ?? "").trim() === name,
  );
  if (!hit) throw new Error(`no button named "${name}"`);
  return hit;
};

export const inputNamed = (root: ParentNode, name: string): HTMLInputElement => {
  const el = root.querySelector<HTMLInputElement>(`input[aria-label="${name}"]`);
  if (!el) throw new Error(`no input named "${name}"`);
  return el;
};

export const selectNamed = (root: ParentNode, name: string): HTMLSelectElement => {
  const el = root.querySelector<HTMLSelectElement>(`select[aria-label="${name}"]`);
  if (!el) throw new Error(`no select named "${name}"`);
  return el;
};

/** The select itself, or the one inside a wrapper (a column cell may be either). */
export const maybeSelectOf = (el: Element): HTMLSelectElement | null =>
  el instanceof HTMLSelectElement ? el : el.querySelector("select");
export const selectOf = (el: Element): HTMLSelectElement => {
  const hit = maybeSelectOf(el);
  if (!hit) throw new Error("no select in this cell");
  return hit;
};

export const switchNamed = (root: ParentNode, name: string): HTMLElement => {
  const el = root.querySelector<HTMLElement>(`[role="switch"][aria-label="${name}"]`);
  if (!el) throw new Error(`no switch named "${name}"`);
  return el;
};

// ---- actions ----

const inputValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;

export async function typeInto(input: HTMLInputElement, value: string): Promise<void> {
  await act(async () => {
    inputValue?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

export async function choose(select: HTMLSelectElement, value: string): Promise<void> {
  await act(async () => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await settle();
}

export async function clickAndSettle(el: Element): Promise<void> {
  await act(async () => {
    (el as HTMLElement).click();
  });
  await settle();
}

/** The option labels of a select, in order, without the empty-value placeholder. */
export const optionNames = (select: HTMLSelectElement): string[] =>
  [...select.options].filter((o) => o.value !== "").map((o) => (o.textContent ?? "").trim());
