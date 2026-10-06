// WEB-12 test helper (not a test): the mount/settle/query helpers the Profile tests share, mirroring
// pages/Team/testApp.ts. Differences from Team (AG-WEB ruling): ProfilePage takes ONLY `{ app }`; its data
// comes from useParkApi(), so the page is mounted inside <ParkProvider api={...}> (WEB-3a, park/app/context).
// The AppCtx fake is `makeApp` in test-support/park/profileApp.ts (it wraps stubApp from appHarness).
// The repo has no @testing-library, so this mounts with react-dom in happy-dom. It lives in the page folder
// and park.static.test.ts reads it as park code: it imports nothing from outside park. No timers: async
// work is flushed with microtasks.
import { type ReactElement, act, createElement } from "react";
import { type Root, createRoot } from "react-dom/client";
import { type Mock, vi } from "vitest";
import { API_METHODS, type Api, type ApiMethod } from "../../api";
import { createFixtureApi } from "../../api/fixtureApi";
import type { AppCtx } from "../../app/AppCtx";
import { ParkProvider } from "../../app/context";
import { ProfilePage } from "./ProfilePage";

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

/** `<ParkProvider api viewport><ProfilePage app/></ParkProvider>`, the fixture-backed spy Api by default. */
export function profileTree(app: AppCtx, api: Api = spyApi()): ReactElement {
  return createElement(ParkProvider, {
    api,
    viewport: { vw: app.vw, vh: app.vh },
    children: createElement(ProfilePage, { app }),
  });
}

/** Mount the page and wait for its data. */
export async function renderProfile(app: AppCtx, api?: Api): Promise<Rendered> {
  const m = mount(profileTree(app, api));
  await settle();
  return { m, root: m.container };
}

// ---- queries (no accessibility tree in happy-dom: roles and names are read from the attributes) ----

export const region = (root: ParentNode, name: string): HTMLElement => {
  const el = root.querySelector<HTMLElement>(`[aria-label="${name}"]`);
  if (!el) throw new Error(`no region named "${name}"`);
  return el;
};

/** The element's own text (its direct text nodes), trimmed: how a visible string is read. */
export const ownText = (el: Element): string =>
  [...el.childNodes]
    .filter((n) => n.nodeType === 3)
    .map((n) => n.textContent ?? "")
    .join("")
    .trim();

/** Every visible string under `root` (own text of every element), as a set. */
export function strings(root: ParentNode): Set<string> {
  const out = new Set<string>();
  for (const el of root.querySelectorAll("*")) {
    if (el.tagName === "STYLE" || el.tagName === "SCRIPT") continue;
    const t = ownText(el);
    if (t) out.add(t);
  }
  return out;
}

export const text = (el: Element | null | undefined): string => (el?.textContent ?? "").trim();

export const buttonNamed = (root: ParentNode, name: string): HTMLButtonElement => {
  const hit = [...root.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => (b.getAttribute("aria-label") ?? b.textContent ?? "").trim() === name,
  );
  if (!hit) throw new Error(`no button named "${name}"`);
  return hit;
};

/** A button whose text content contains `part` (cards that are one button: time of day, Open the Ledger). */
export const buttonWith = (root: ParentNode, part: string): HTMLButtonElement => {
  const hit = [...root.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
    (b.textContent ?? "").includes(part),
  );
  if (!hit) throw new Error(`no button containing "${part}"`);
  return hit;
};

export const switchNamed = (root: ParentNode, name: string): HTMLElement => {
  const el = root.querySelector<HTMLElement>(`[role="switch"][aria-label="${name}"]`);
  if (!el) throw new Error(`no switch named "${name}"`);
  return el;
};

/** Every switch under `root`, as `[aria-label, aria-checked]`, in document order. */
export const switchStates = (root: ParentNode): [string, string][] =>
  [...root.querySelectorAll<HTMLElement>('[role="switch"]')].map((s) => [
    s.getAttribute("aria-label") ?? "",
    s.getAttribute("aria-checked") ?? "",
  ]);

/** The design marks a choice with aria-pressed; a radio-style control (aria-checked) is accepted too. */
export const pressedOf = (el: Element): string | null =>
  el.getAttribute("aria-pressed") ?? el.getAttribute("aria-checked");

/** The settings navigation (aria-label "Settings") and one of its tab buttons by its label. */
export const settingsNav = (root: ParentNode): HTMLElement => region(root, "Settings");
export const tabNamed = (root: ParentNode, label: string): HTMLButtonElement => {
  const hit = [...settingsNav(root).querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => text(b) === label,
  );
  if (!hit) throw new Error(`no tab named "${label}"`);
  return hit;
};

/** A profile form field by its visible label: the <label> that starts with it and its <input>. */
export function fieldInput(root: ParentNode, label: string): HTMLInputElement {
  const wrap = [...root.querySelectorAll("label")].find((l) => text(l).startsWith(label));
  const byWrap = wrap?.querySelector("input");
  const byFor = wrap?.htmlFor ? root.querySelector<HTMLInputElement>(`#${wrap.htmlFor}`) : null;
  const hit = byWrap ?? byFor;
  if (!hit) throw new Error(`no field labelled "${label}"`);
  return hit;
}

// ---- actions ----

const inputValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;

export async function typeInto(input: HTMLInputElement, value: string): Promise<void> {
  await act(async () => {
    inputValue?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle();
}

export async function clickAndSettle(el: Element): Promise<void> {
  await act(async () => {
    (el as HTMLElement).click();
  });
  await settle();
}

/** Switch to a settings tab by clicking it. */
export const openTab = (root: ParentNode, label: string): Promise<void> =>
  clickAndSettle(tabNamed(root, label));
