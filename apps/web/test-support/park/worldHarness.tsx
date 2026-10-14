// WEB-6 test support: mount the World page the way the shell does (inside ParkProvider with a spied fixture
// Api, a fake scheduler and a fixed viewport), plus the small DOM readers the World tests share. The page is
// found by its public surface only: roles, labels and visible text. Nothing here is bundled.
import { act } from "react";
import { type Mock, vi } from "vitest";
import type { HttpClient } from "../../src/api/http";
import { API_METHODS, type Api } from "../../src/park/api/index";
import type { Dec, World } from "../../src/park/api/types";
import type { AppCtx } from "../../src/park/app/AppCtx";
import { ParkProvider } from "../../src/park/app/context";
import { WorldPage } from "../../src/park/pages/World/WorldPage";
import { type SpyApi, fakeApi, fakeScheduler, stubApp } from "./appHarness";
import { type Mounted, mount, q, qa } from "./componentsHarness";

type Sched = ReturnType<typeof fakeScheduler>;

/** The fixture Api with the reads the World page makes spied on, next to the spied writes. */
export type SpiedApi = SpyApi & {
  getWorlds: Mock;
  getPlans: Mock;
  getDecisions: Mock;
  getSkills: Mock;
  getConnectors: Mock;
};

export function spiedApi(): SpiedApi {
  const base = fakeApi();
  return {
    ...base,
    getWorlds: vi.fn(base.getWorlds),
    getPlans: vi.fn(base.getPlans),
    getDecisions: vi.fn(base.getDecisions),
    getSkills: vi.fn(base.getSkills),
    getConnectors: vi.fn(base.getConnectors),
  } as SpiedApi;
}

/**
 * The spied fixture Api whose world list reports `source: "live"`, as the live Api's does. Only a world whose
 * data came from the live API has a stage to link to (WEB-CUTOVER).
 */
export function liveWorldsApi(): SpiedApi {
  const base = spiedApi();
  return {
    ...base,
    getWorlds: vi.fn(async (...a: Parameters<typeof base.getWorlds>) => ({
      ...(await base.getWorlds(...a)),
      source: "live" as const,
    })),
  } as SpiedApi;
}

/** An Api whose every call is still waiting: the page's loading state. */
export function pendingApi(): Api {
  const never = () => new Promise(() => undefined);
  return Object.fromEntries(API_METHODS.map((m) => [m, never])) as unknown as Api;
}

const KEYS = ["depot", "mail"] as const;
const needsOf = (dec: Dec) => KEYS.filter((k) => !dec[k]).length;

/** The AppCtx of the reference for a world id and a set of decisions (needsLeft follows from `dec`). */
export function appFor(id: string | null, dec: Dec = {}, over: Partial<AppCtx> = {}): AppCtx {
  return stubApp("world", {
    params: id === null ? {} : { id },
    dec,
    needsLeft: needsOf(dec),
    ...over,
  });
}

export const NIGHT: Partial<AppCtx> = { time: "night", night: true };

export interface WorldRig {
  readonly m: Mounted;
  readonly el: HTMLElement;
  readonly api: Api;
  readonly sch: Sched;
  readonly navigate: Mock;
  app: AppCtx;
  /** Re-render with a changed AppCtx (same spies and same mounted page), as the shell does. */
  update(over: Partial<AppCtx>): Promise<void>;
  /** Approve or undo decisions: `dec` and `needsLeft` change together, as in the store. */
  setDec(dec: Dec): Promise<void>;
  /** Open another world in the same mounted page (the route's `id` changes). */
  open(id: string): Promise<void>;
}

export interface RigOptions {
  /** The world id in `app.params`; `null` leaves it out. Default "k1". */
  id?: string | null;
  api?: Api;
  dec?: Dec;
  added?: World[];
  app?: Partial<AppCtx>;
  /** A demo session (QA-DEMO-1): recorded sample data, no real outcomes. */
  demo?: boolean;
  /** The run client the page reads recorded events from (UI-10 B8); the default client when absent. */
  client?: HttpClient;
}

export async function settle(): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await act(async () => {
      await new Promise<void>((r) => setTimeout(r, 0));
    });
  }
}

export async function mountWorld(opts: RigOptions = {}): Promise<WorldRig> {
  const api = opts.api ?? spiedApi();
  const sch = fakeScheduler();
  const navigate = vi.fn();
  const over: Partial<AppCtx> = { ...(opts.added ? { added: opts.added } : {}), ...opts.app };
  const rig: WorldRig = {
    app: appFor(opts.id === undefined ? "k1" : opts.id, opts.dec ?? {}, over),
    api,
    sch,
    navigate,
    m: undefined as unknown as Mounted,
    el: undefined as unknown as HTMLElement,
    update: async (patch) => {
      rig.app = { ...rig.app, ...patch };
      rig.m.render(tree(rig.app));
      await settle();
    },
    setDec: async (dec) => rig.update({ dec, needsLeft: needsOf(dec) }),
    open: async (id) => rig.update({ params: { id } }),
  };
  const tree = (app: AppCtx) => {
    const page = (
      <ParkProvider
        api={api}
        navigate={navigate}
        schedule={sch.schedule}
        viewport={{ vw: app.vw, vh: app.vh }}
        {...(opts.demo ? { demo: true } : {})}
        {...(opts.client ? { worldClient: opts.client } : {})}
      >
        <WorldPage app={app} />
      </ParkProvider>
    );
    return page;
  };
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
export const pageText = (root: ParentNode): string => squash((root as HTMLElement).textContent);

const ACTIONS = 'button, a, [role="button"], [role="link"]';

/** The control whose whole text is `label`. */
export function control(root: ParentNode, label: string): HTMLElement {
  const hit = qa(root, ACTIONS).find((e) => textOf(e) === label);
  if (!hit) throw new Error(`no control labelled "${label}"`);
  return hit;
}
export const hasControl = (root: ParentNode, label: string): boolean =>
  qa(root, ACTIONS).some((e) => textOf(e) === label);
/** The control whose text, whitespace removed, is `label` whitespace removed (a monogram beside a name). */
export function controlFlat(root: ParentNode, label: string): HTMLElement {
  const hit = qa(root, ACTIONS).find((e) => flat(textOf(e)) === flat(label));
  if (!hit) throw new Error(`no control reading "${label}"`);
  return hit;
}
export const controls = (root: ParentNode): HTMLElement[] => qa(root, ACTIONS);

/** The innermost element whose whole text is `text`. */
export function elWithText(root: ParentNode, text: string): HTMLElement | undefined {
  return qa(root, "*")
    .filter((e) => textOf(e) === text)
    .pop();
}
/** The innermost element whose text, whitespace removed, is `text` whitespace removed. */
export function elWithFlat(root: ParentNode, text: string): HTMLElement | undefined {
  return qa(root, "*")
    .filter((e) => flat(textOf(e)) === flat(text))
    .pop();
}

/** The first ancestor-or-self of `el` for which `ok` holds. */
export function climb(el: Element | undefined, ok: (n: HTMLElement) => boolean): HTMLElement {
  for (let n = el as HTMLElement | null | undefined; n; n = n.parentElement) if (ok(n)) return n;
  throw new Error("no ancestor matches");
}

/** What a picture of the engines is in the DOM. */
export const ART = "img, svg";

/**
 * The map block of the reference: the 440px box that holds the world art and, as its direct child, the
 * hero tag. It is the nearest ancestor of the tag's text that holds the art: the engines draw a world, a
 * building or an agent as an <img> (an SVG blob) or an inline <svg>.
 */
export function mapBlock(root: ParentNode, heroTag: string): HTMLElement {
  const tag = elWithText(root, heroTag);
  if (!tag) throw new Error(`no hero tag reading "${heroTag}"`);
  return climb(tag, (n) => n.querySelector(ART) !== null);
}

export const region = (root: ParentNode, label: string): HTMLElement =>
  q(root, `section[aria-label="${label}"]`);
export const breadcrumb = (root: ParentNode): HTMLElement =>
  q(root, 'nav[aria-label="Breadcrumb"]');

/** The row of a list: the smallest ancestor of the element reading `anchor` whose text holds `inside`. */
export function rowOf(scope: ParentNode, anchor: string, inside: string): HTMLElement {
  const a = elWithText(scope, anchor);
  if (!a) throw new Error(`nothing reads "${anchor}"`);
  return climb(a, (n) => textOf(n).includes(inside));
}

/** The progress a bar shows, 0..100: aria-valuenow of a progressbar, else an inline `width: N%`. */
export function progressOf(row: Element): number | null {
  const bar = row.querySelector('[role="progressbar"]');
  if (bar) return Number(bar.getAttribute("aria-valuenow"));
  for (const el of qa<HTMLElement>(row, "*")) {
    if (/^\d+(\.\d+)?%$/.test(el.style.width)) return Number.parseFloat(el.style.width);
  }
  return null;
}
/** The bar that sits beside a label: the first ancestor (within four levels) that holds a bar. */
export function progressBeside(label: Element): number | null {
  let n: Element | null = label.parentElement;
  for (let i = 0; i < 4 && n; i++, n = n.parentElement) {
    const p = progressOf(n);
    if (p !== null) return p;
  }
  return null;
}

/** A real browser click: reports whether the default action was left alone (false = prevented). */
export function clickEl(el: Element, init: MouseEventInit = {}): boolean {
  let proceeded = true;
  act(() => {
    proceeded = el.dispatchEvent(
      new MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ...init }),
    );
  });
  return proceeded;
}
export const MODIFIED: readonly [string, MouseEventInit][] = [
  ["ctrl", { ctrlKey: true }],
  ["cmd", { metaKey: true }],
  ["shift", { shiftKey: true }],
  ["alt", { altKey: true }],
  ["middle button", { button: 1 }],
];

/** The last `app.go` call: [page, params]. */
export function lastGo(app: AppCtx): [unknown, unknown] | undefined {
  const calls = (app.go as unknown as Mock).mock.calls;
  const last = calls[calls.length - 1];
  return last ? [last[0], last[1]] : undefined;
}
export const goCalls = (app: AppCtx): number => (app.go as unknown as Mock).mock.calls.length;
export const toastCalls = (app: AppCtx): unknown[][] => (app.toast as unknown as Mock).mock.calls;
export const decideCalls = (app: AppCtx): unknown[][] => (app.decide as unknown as Mock).mock.calls;

/** Replaces navigator.clipboard for one test; returns the spy and a restore function. */
export function stubClipboard(writeText: Mock): () => void {
  const had = Object.getOwnPropertyDescriptor(navigator, "clipboard");
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return () => {
    if (had) Object.defineProperty(navigator, "clipboard", had);
    else Reflect.deleteProperty(navigator, "clipboard");
  };
}

/** The element of the page that holds both the map card and the side column (inline grid columns). */
export function topGridColumns(root: ParentNode, heroTag: string): string {
  const map = mapBlock(root, heroTag);
  for (let n: HTMLElement | null = map.parentElement; n; n = n.parentElement) {
    const cols = n.style.getPropertyValue("grid-template-columns");
    if (cols) return cols.replace(/\s+/g, "");
  }
  throw new Error("no ancestor of the map sets grid-template-columns inline");
}
