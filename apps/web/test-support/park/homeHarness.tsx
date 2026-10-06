// WEB-4 test support: mount the Home page the way the shell does (inside ParkProvider with a spied fixture
// Api, a fake scheduler and a fixed viewport), plus the small DOM readers the Home tests share. The page
// is found by its public surface only: roles, labels and visible text. Nothing here is bundled.
import { act } from "react";
import { type Mock, vi } from "vitest";
import { API_METHODS, type Api } from "../../src/park/api/index";
import type { Dec } from "../../src/park/api/types";
import type { AppCtx } from "../../src/park/app/AppCtx";
import { ParkProvider } from "../../src/park/app/context";
import { HomePage } from "../../src/park/pages/Home/HomePage";
import { type SpyApi, fakeApi, fakeScheduler, stubApp } from "./appHarness";
import { type Mounted, mount, q, qa } from "./componentsHarness";

type Sched = ReturnType<typeof fakeScheduler>;

/** The fixture Api with the reads the Home page makes spied on, next to the spied writes. */
export type SpiedApi = SpyApi & {
  getUser: Mock;
  getToday: Mock;
  getWorlds: Mock;
  getAgenda: Mock;
  getLedger: Mock;
};

export function spiedApi(): SpiedApi {
  const base = fakeApi();
  return {
    ...base,
    getUser: vi.fn(base.getUser),
    getToday: vi.fn(base.getToday),
    getWorlds: vi.fn(base.getWorlds),
    getAgenda: vi.fn(base.getAgenda),
    getLedger: vi.fn(base.getLedger),
  } as SpiedApi;
}

/** An Api whose every call is still waiting: the page's loading state. */
export function pendingApi(): Api {
  const never = () => new Promise(() => undefined);
  return Object.fromEntries(API_METHODS.map((m) => [m, never])) as unknown as Api;
}

/** The AppCtx of the reference for a given set of decisions (needsLeft follows from `dec`). */
export function appFor(dec: Dec = {}, over: Partial<AppCtx> = {}): AppCtx {
  const needsLeft = (["depot", "mail"] as const).filter((k) => !dec[k]).length;
  return stubApp("home", { dec, needsLeft, ...over });
}

export const NIGHT: Partial<AppCtx> = { time: "night", night: true };

export interface HomeRig {
  readonly m: Mounted;
  readonly el: HTMLElement;
  readonly api: Api;
  readonly sch: Sched;
  readonly navigate: Mock;
  app: AppCtx;
  /** Re-render with a changed AppCtx (same spies), as the shell does when `dec`, `added` or `vw` change. */
  update(over: Partial<AppCtx>): Promise<void>;
  /** Approve or undo decisions: `dec` and `needsLeft` change together, as in the store. */
  setDec(dec: Dec): Promise<void>;
}

export interface RigOptions {
  api?: Api;
  dec?: Dec;
  app?: Partial<AppCtx>;
}

export async function settle(): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await act(async () => {
      await new Promise<void>((r) => setTimeout(r, 0));
    });
  }
}

export async function mountHome(opts: RigOptions = {}): Promise<HomeRig> {
  const api = opts.api ?? spiedApi();
  const sch = fakeScheduler();
  const navigate = vi.fn();
  const rig: HomeRig = {
    app: appFor(opts.dec ?? {}, opts.app ?? {}),
    api,
    sch,
    navigate,
    m: undefined as unknown as Mounted,
    el: undefined as unknown as HTMLElement,
    update: async (over) => {
      rig.app = { ...rig.app, ...over };
      rig.m.render(tree(rig.app));
      await settle();
    },
    setDec: async (dec) => {
      const needsLeft = (["depot", "mail"] as const).filter((k) => !dec[k]).length;
      await rig.update({ dec, needsLeft });
    },
  };
  const tree = (app: AppCtx) => (
    <ParkProvider
      api={api}
      navigate={navigate}
      schedule={sch.schedule}
      viewport={{ vw: app.vw, vh: app.vh }}
    >
      <HomePage app={app} />
    </ParkProvider>
  );
  const m = mount(tree(rig.app));
  Object.assign(rig, { m, el: m.container });
  await settle();
  return rig;
}

// ---- readers ---------------------------------------------------------------------------------

export const squash = (s: string | null | undefined): string =>
  (s ?? "").replace(/\s+/g, " ").trim();
export const textOf = (el: Element): string => squash(el.textContent);
/** Text with all whitespace removed: compares composite controls whatever spaces sit between their spans. */
export const flat = (s: string | null | undefined): string => (s ?? "").replace(/\s+/g, "");

export const todayRegion = (root: ParentNode): HTMLElement => q(root, 'aside[aria-label="Today"]');
export const taskInput = (root: ParentNode): HTMLInputElement =>
  q<HTMLInputElement>(root, 'input[aria-label="Describe your task"]');

/** The "Size of job" control: a labelled radiogroup (the WEB-2 component) or tablist (the reference). */
export function sizeGroup(root: ParentNode): HTMLElement {
  const g = q(root, '[aria-label="Size of job"]');
  const role = g.getAttribute("role");
  if (role !== "radiogroup" && role !== "tablist") {
    throw new Error(`"Size of job" has role ${role}, expected radiogroup or tablist`);
  }
  return g;
}
export const sizeOptions = (root: ParentNode): HTMLElement[] =>
  qa(sizeGroup(root), '[role="radio"], [role="tab"]');
export const isSelected = (el: Element): boolean =>
  el.getAttribute("aria-checked") === "true" || el.getAttribute("aria-selected") === "true";
export const selectedSize = (root: ParentNode): string =>
  textOf(sizeOptions(root).find(isSelected) ?? document.body);

const ACTIONS = 'button, a, [role="button"], [role="link"]';

/** The control whose whole text is `label`. */
export function control(root: ParentNode, label: string): HTMLElement {
  const hit = qa(root, ACTIONS).find((e) => textOf(e) === label);
  if (!hit) throw new Error(`no control labelled "${label}"`);
  return hit;
}
export const hasControl = (root: ParentNode, label: string): boolean =>
  qa(root, ACTIONS).some((e) => textOf(e) === label);

/** The control whose text contains `part` (a row of the live list, the needs pill, a pin). */
export function controlWith(root: ParentNode, part: string): HTMLElement {
  const hit = qa(root, ACTIONS).find((e) => textOf(e).includes(part));
  if (!hit) throw new Error(`no control containing "${part}"`);
  return hit;
}

/** The map pins of a world: controls outside the Today panel whose text starts with the world's name. */
export function pinsFor(root: ParentNode, name: string): HTMLElement[] {
  const today = root.querySelector('aside[aria-label="Today"]');
  return qa(root, ACTIONS).filter((e) => !today?.contains(e) && textOf(e).startsWith(name));
}
export function pinFor(root: ParentNode, name: string): HTMLElement {
  const hit = pinsFor(root, name)[0];
  if (!hit) throw new Error(`no map pin for "${name}"`);
  return hit;
}

/** Everything in the page the person can read, for "nothing like this shows" checks. */
export const pageText = (root: ParentNode): string => squash((root as HTMLElement).textContent);

/** A real browser click: reports whether the default action was left alone (false = prevented). */
export function clickEl(el: Element): boolean {
  let proceeded = true;
  act(() => {
    proceeded = el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
  return proceeded;
}

/** Types into a controlled input the way a browser delivers it: value set, then an input event. */
export function typeInto(input: HTMLInputElement, value: string): void {
  act(() => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

/** The last `app.go` call: [page, params]. */
export function lastGo(app: AppCtx): [unknown, unknown] | undefined {
  const calls = (app.go as unknown as Mock).mock.calls;
  const last = calls[calls.length - 1];
  return last ? [last[0], last[1]] : undefined;
}
export const goCalls = (app: AppCtx): number => (app.go as unknown as Mock).mock.calls.length;

/** The progress a row shows, 0..100: aria-valuenow of a progressbar, else an inline `width: N%`. */
export function progressOf(row: Element): number | null {
  const bar = row.querySelector('[role="progressbar"]');
  if (bar) return Number(bar.getAttribute("aria-valuenow"));
  for (const el of qa<HTMLElement>(row, "*")) {
    if (/^\d+(\.\d+)?%$/.test(el.style.width)) return Number.parseFloat(el.style.width);
  }
  return null;
}

/** Where a pin sits: inline left/top in px on the element or the nearest ancestor that sets them. */
export function placedAt(el: HTMLElement, stop: HTMLElement): { x: number; y: number } | null {
  for (let n: HTMLElement | null = el; n && n !== stop; n = n.parentElement) {
    if (n.style.left && n.style.top) {
      return { x: Number.parseFloat(n.style.left), y: Number.parseFloat(n.style.top) };
    }
  }
  return null;
}

/** The innermost element whose whole text is `text` (case-insensitive when `ci`). */
export function elWithText(root: ParentNode, text: string, ci = false): HTMLElement | undefined {
  const same = (a: string) => (ci ? a.toLowerCase() === text.toLowerCase() : a === text);
  return qa(root, "*")
    .filter((e) => same(textOf(e)))
    .pop();
}
