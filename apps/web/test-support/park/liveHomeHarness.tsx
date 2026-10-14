// FR-UX-13 test support: the Home page mounted inside the real ParkProvider with the real store, so the live
// composer's whole path (confirm -> Api.startWorld -> store -> toast and added worlds) is exercised, not a stub
// `app`. The Api is injected: `liveSourced` marks every result "live" (the store switches to its live
// behaviour when an Api result says so, as WIRE-3's `decide` does), and `Gate` holds a reply until a test
// releases it. Nothing here is bundled and nothing touches the network.
import { type Mock, vi } from "vitest";
import { makeWorld } from "../../src/park/api/fixtures/worlds";
import { API_METHODS, type Api, type ApiMethod } from "../../src/park/api/index";
import type { ApiResult, StartAck, TierKey, World } from "../../src/park/api/types";
import { ParkProvider, usePageApp, useParkStore } from "../../src/park/app/context";
import type { ParkStore } from "../../src/park/app/store";
import { HomePage } from "../../src/park/pages/Home/HomePage";
import { fakeApi, fakeScheduler } from "./appHarness";
import { type Mounted, mount } from "./componentsHarness";
import { MODES } from "./homeCopy";
import {
  clickEl,
  control,
  hasControl,
  pageText,
  settle,
  sizeOptions,
  taskInput,
  textOf,
  typeInto,
} from "./homeHarness";

type AnyCall = (...args: unknown[]) => Promise<ApiResult<unknown>>;

/** The fixture Api with every result's source changed to "live": a stand-in for a configured deployment. */
export function liveSourced(over: Partial<Api> = {}): Api {
  const base = fakeApi() as unknown as Record<ApiMethod, AnyCall>;
  const wrapped = Object.fromEntries(
    API_METHODS.map((name) => [
      name,
      (...args: unknown[]) => base[name](...args).then((r) => ({ ...r, source: "live" as const })),
    ]),
  );
  return { ...(wrapped as unknown as Api), ...over };
}

/** A promise a test settles by hand. */
export interface Gate<T> {
  readonly promise: Promise<T>;
  resolve(value: T): void;
  reject(reason: unknown): void;
}
export function gate<T>(): Gate<T> {
  let resolve: (v: T) => void = () => undefined;
  let reject: (e: unknown) => void = () => undefined;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** What the live Api's `startWorld` resolves with: a world the server's reply made. */
export const liveAck = (world: World): ApiResult<StartAck> => ({
  data: { ok: true, world },
  source: "live",
});

/** A world the server named (the fixture's `makeWorld` shape, with the server's own id). */
export const serverWorld = (mode: TierKey, text: string, id: string): World => ({
  ...makeWorld(mode, text, 1),
  id,
});

export interface LiveRig {
  readonly m: Mounted;
  readonly el: HTMLElement;
  readonly api: Api;
  readonly store: ParkStore;
  readonly navigate: Mock;
  readonly sch: ReturnType<typeof fakeScheduler>;
}

/** Home with the real store. `api` must already be live-sourced (or fixture, for the unchanged path). */
export async function mountLiveHome(api: Api): Promise<LiveRig> {
  const held = {} as { store: ParkStore };
  function Probe() {
    held.store = useParkStore();
    return null;
  }
  function Page() {
    return <HomePage app={usePageApp()} />;
  }
  const sch = fakeScheduler();
  const navigate = vi.fn();
  const m = mount(
    <ParkProvider
      api={api}
      navigate={navigate}
      schedule={sch.schedule}
      viewport={{ vw: 1440, vh: 900 }}
    >
      <Probe />
      <Page />
    </ParkProvider>,
  );
  await settle();
  return { m, el: m.container, api, store: held.store, navigate, sch };
}

const DRAFT_MS = 900;

export async function pickSize(rig: LiveRig, label: string): Promise<void> {
  const option = sizeOptions(rig.el).find((o) => textOf(o) === label);
  if (!option) throw new Error(`no size option ${label}`);
  clickEl(option);
  await settle();
}

/** Types the brief, taps the start control, lets the 900 ms draft land: the plan card is up. */
export async function toPlan(rig: LiveRig, text: string): Promise<void> {
  typeInto(taskInput(rig.el), text);
  const start = MODES.map((m) => m.start).find((l) => hasControl(rig.el, l)) ?? "";
  clickEl(control(rig.el, start));
  await settle();
  for (const t of rig.sch.live().filter((x) => x.ms === DRAFT_MS)) rig.sch.fire(t);
  await settle();
}

/** The confirm control of the plan card for the size on screen. */
export function confirmButton(rig: LiveRig): HTMLElement {
  const label = MODES.map((m) => m.confirm).find((l) => hasControl(rig.el, l));
  if (!label) throw new Error("no confirm control: the plan card is not open");
  return control(rig.el, label);
}
export const hasConfirm = (rig: LiveRig): boolean =>
  MODES.some((m) => hasControl(rig.el, m.confirm));

export async function confirm(rig: LiveRig): Promise<void> {
  clickEl(confirmButton(rig));
  await settle();
}

/** Everything a person can read: the page and the toast the store holds (the shell draws the toast). */
export function said(rig: LiveRig): string {
  const t = rig.store.getState().toast;
  return `${pageText(rig.el)} ${t?.message ?? ""} ${t?.actionLabel ?? ""}`.replace(/\s+/g, " ");
}

/** What is announced to a person: the toast's message and the text of every alert or status region. */
export function notices(rig: LiveRig): string[] {
  const regions = [...rig.el.querySelectorAll('[role="alert"], [role="status"]')].map(textOf);
  return [rig.store.getState().toast?.message ?? "", ...regions].filter((t) => t.length > 0);
}

/** True when the page or the toast says a request is on its way, not just that a control exists. */
export function showsPending(rig: LiveRig): boolean {
  const buttons = [...rig.el.querySelectorAll<HTMLElement>("button")].filter(
    (b) => !b.closest(".park-home-intake") || b.classList.contains("park-home-start"),
  );
  const busy = buttons.some(
    (b) =>
      (b as HTMLButtonElement).disabled ||
      b.getAttribute("aria-disabled") === "true" ||
      b.getAttribute("aria-busy") === "true",
  );
  const status = [...rig.el.querySelectorAll('[role="status"]')].some((e) =>
    /start|sending|working|wait/i.test(textOf(e)),
  );
  return busy || status;
}

/** Did "Open" (or the loader) take the person to the world with this id? */
export function opened(rig: LiveRig, id: string): boolean {
  const went = rig.navigate.mock.calls.some((c) => String(c[0]).includes(encodeURIComponent(id)));
  return went || rig.store.getState().wl?.id === id;
}
