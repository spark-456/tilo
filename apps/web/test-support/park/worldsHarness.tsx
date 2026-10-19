// WEB-5 test support: mounts the Worlds page the way the shell does (a ParkProvider with a spied fixture
// Api, an AppCtx from stubApp) and reads it back through roles, text and attributes, never class names.
// The page module is imported lazily so a missing page fails each test, not the whole file.
import { type ComponentType, act } from "react";
import { vi } from "vitest";
import { createFixtureApi } from "../../src/park/api/fixtureApi";
import * as fx from "../../src/park/api/fixtures";
import type { Api } from "../../src/park/api/index";
import type { Dec, World } from "../../src/park/api/types";
import type { AppCtx } from "../../src/park/app/AppCtx";
import { ParkProvider } from "../../src/park/app/context";
import { parkPath } from "../../src/park/app/router";
import { deepFreeze, stubApp } from "./appHarness";
import { type Mounted, mount, qa } from "./componentsHarness";

export type WorldsApi = Api & {
  getWorlds: ReturnType<typeof vi.fn>;
  getDecisions: ReturnType<typeof vi.fn>;
};

/** The fixture Api with the two reads the page makes spied on; `worlds` replaces the world list. */
export function worldsApi(worlds?: (dec: Dec, added: readonly World[]) => World[]): WorldsApi {
  const base = createFixtureApi();
  return {
    ...base,
    getWorlds: vi.fn(
      worlds
        ? (d: Dec, a: readonly World[]) =>
            Promise.resolve({ data: worlds(d, a), source: "fixture" as const })
        : base.getWorlds,
    ),
    getDecisions: vi.fn(base.getDecisions),
  } as WorldsApi;
}

export const flush = async (): Promise<void> => {
  for (let i = 0; i < 4; i++) await act(async () => Promise.resolve());
};

export interface Rendered {
  m: Mounted;
  c: HTMLElement;
  app: AppCtx;
  api: WorldsApi;
  /** Mount the same page again with a new `dec` / `added` (the shell re-renders on every store change). */
  update(next: { dec?: Dec; added?: World[] }): Promise<AppCtx>;
}

export async function renderWorlds(
  opts: { dec?: Dec; added?: World[]; api?: WorldsApi } = {},
): Promise<Rendered> {
  // The specifier is a variable so a missing page fails the tests that need it, not the import analysis of every file.
  const page = "../../src/park/pages/Worlds/WorldsPage";
  const { WorldsPage } = (await import(/* @vite-ignore */ page)) as {
    WorldsPage: ComponentType<{ app: AppCtx }>;
  };
  const api = opts.api ?? worldsApi();
  const ctx = (dec: Dec, added: World[]): AppCtx =>
    stubApp("worlds", {
      dec: deepFreeze({ ...dec }),
      added: deepFreeze([...added]),
      needsLeft: fx.needsLeft(dec),
    });
  const first = ctx(opts.dec ?? {}, opts.added ?? []);
  const m = mount(
    <ParkProvider api={api}>
      <WorldsPage app={first} />
    </ParkProvider>,
  );
  await flush();
  const r: Rendered = {
    m,
    c: m.container,
    app: first,
    api,
    async update(next) {
      const app = ctx(next.dec ?? {}, next.added ?? []);
      m.render(
        <ParkProvider api={api}>
          <WorldsPage app={app} />
        </ParkProvider>,
      );
      await flush();
      r.app = app;
      return app;
    },
  };
  return r;
}

/** A controlled input's change, the way a browser delivers it (React listens for `input`). */
export function typeInto(input: HTMLInputElement, value: string): void {
  act(() => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

export const hrefOf = (id: string): string => parkPath("world", { id });
const idOf = (a: Element): string =>
  decodeURIComponent((a.getAttribute("href") ?? "").split("/").pop() ?? "");

export const section = (c: ParentNode, label: string): HTMLElement | null =>
  c.querySelector<HTMLElement>(`section[aria-label="${label}"]`);
/** World ids of the cards in a section, in DOM order ([] when the section is absent). */
export const cardIds = (c: ParentNode, label: string): string[] =>
  qa(section(c, label) ?? document.createElement("div"), "a[href]").map(idOf);
export const card = (c: ParentNode, id: string): HTMLAnchorElement => {
  const a = c.querySelector<HTMLAnchorElement>(`a[href="${hrefOf(id)}"]`);
  if (!a) throw new Error(`no card for world ${id}`);
  return a;
};

export const statusTabs = (c: ParentNode): HTMLButtonElement[] =>
  qa<HTMLButtonElement>(c, '[role="tablist"][aria-label="Status"] [role="tab"]');
export const tab = (c: ParentNode, label: string): HTMLButtonElement => {
  const t = statusTabs(c).find((b) => b.textContent?.replace(/\d+$/, "") === label);
  if (!t) throw new Error(`no status tab ${label}`);
  return t;
};
/** `{ All: 11, "Needs you": 1, ... }` from the tab texts ("All" + "11"). */
export const tabCounts = (c: ParentNode): Record<string, number> =>
  Object.fromEntries(
    statusTabs(c).map((t) => {
      const m = /^(.*?)(\d+)$/.exec(t.textContent ?? "");
      return [m?.[1] ?? "", Number(m?.[2])];
    }),
  );
export const scaleButton = (c: ParentNode, label: string): HTMLButtonElement => {
  const b = qa<HTMLButtonElement>(c, "button[aria-pressed]").find((x) => x.textContent === label);
  if (!b) throw new Error(`no scale button ${label}`);
  return b;
};
export const buttons = (c: ParentNode, text: string): HTMLButtonElement[] =>
  qa<HTMLButtonElement>(c, "button").filter((b) => b.textContent?.trim() === text);
export const search = (c: ParentNode): HTMLInputElement =>
  c.querySelector<HTMLInputElement>('input[aria-label="Search worlds"]') ??
  (() => {
    throw new Error("no search input");
  })();

/** The deepest element whose whole text is `text`. */
export function leaf(root: ParentNode, text: string): HTMLElement | null {
  const hits = qa(root, "*").filter((e) => e.textContent?.trim() === text);
  return hits.find((e) => !hits.some((o) => o !== e && e.contains(o))) ?? null;
}
/** The amber "WAITING FOR YOU" box: the first ancestor of its label that also holds a decision card. */
export function spotlight(c: ParentNode): HTMLElement {
  let cur = leaf(c, "WAITING FOR YOU");
  const title =
    leaf(c, "Laptop Depot · budget sign-off") ?? leaf(c, "Mail Room gate · supplier brief");
  while (cur && title && !cur.contains(title)) cur = cur.parentElement;
  if (!cur) throw new Error("no spotlight");
  return cur;
}
/** The ancestor of `el` that is a direct child of `root`. */
export function childOf(root: Element, el: Element): HTMLElement | null {
  let cur: Element | null = el;
  while (cur && cur.parentElement !== root) cur = cur.parentElement;
  return cur as HTMLElement | null;
}
