// WEB-8a test support: mount the Skills page the way the shell does (inside ParkProvider with a spied
// fixture Api, a fake clock behind the injected `schedule` and a fixed viewport), plus the small DOM readers
// and drivers the Skills tests share. The page is found by its public surface only: roles, labels and
// visible text. Nothing here is bundled.
import { resolveObjectURL } from "node:buffer";
import { type ReactNode, act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { type Mock, vi } from "vitest";
import { createFixtureApi } from "../../src/park/api/fixtureApi";
import { API_METHODS, type Api } from "../../src/park/api/index";
import type { ApiResult } from "../../src/park/api/types";
import type { AppCtx } from "../../src/park/app/AppCtx";
import { ParkProvider } from "../../src/park/app/context";
import { createKit } from "../../src/park/engines/kit";
import type { AgentSpec, H } from "../../src/park/engines/types";
import { SkillsPage } from "../../src/park/pages/Skills/SkillsPage";
import { stubApp } from "./appHarness";
import { type Mounted, mount, press, q, qa } from "./componentsHarness";
import { STEP_LABELS } from "./skillsCopy";

// ---- fake clock ------------------------------------------------------------------------------------

export interface ClockTimer {
  readonly ms: number;
  readonly at: number;
  readonly fn: () => void;
  cancelled: boolean;
  fired: boolean;
}

/**
 * `schedule(fn, ms)` returns a cancel function (the pinned signature). Nothing runs by itself: `advance(ms)`
 * moves a virtual clock and runs, in due order and one `act` each (so effects flush between timers), every
 * timer that is neither cancelled nor fired and falls due, including those a firing timer schedules.
 */
export function fakeClock() {
  let now = 0;
  const timers: ClockTimer[] = [];
  const schedule = vi.fn((fn: () => void, ms: number): (() => void) => {
    const t: ClockTimer = { ms, at: now + ms, fn, cancelled: false, fired: false };
    timers.push(t);
    return () => {
      t.cancelled = true;
    };
  });
  const live = (): ClockTimer[] => timers.filter((t) => !t.cancelled && !t.fired);
  function advance(ms: number): void {
    const target = now + ms;
    for (let guard = 0; guard < 500; guard++) {
      const next = live()
        .filter((t) => t.at <= target)
        .sort((a, b) => a.at - b.at)[0];
      if (!next) break;
      now = next.at;
      next.fired = true;
      act(() => {
        next.fn();
      });
    }
    now = target;
  }
  return { schedule, timers, live, advance, now: () => now };
}
export type Clock = ReturnType<typeof fakeClock>;

// ---- Apis ------------------------------------------------------------------------------------------

export type SkillsApi = Api & { getSkills: Mock; getLearn: Mock; saveSkill: Mock };

/** The fixture Api with the two reads and the one write the Skills page makes spied on. */
export function skillsApi(over: Partial<Api> = {}): SkillsApi {
  const merged: Api = { ...createFixtureApi(), ...over };
  return {
    ...merged,
    getSkills: vi.fn(merged.getSkills),
    getLearn: vi.fn(merged.getLearn),
    saveSkill: vi.fn(merged.saveSkill),
  } as SkillsApi;
}

/** An Api whose every call is still waiting: the page's loading state. */
export function pendingApi(): Api {
  const never = () => new Promise(() => undefined);
  return Object.fromEntries(API_METHODS.map((m) => [m, never])) as unknown as Api;
}

export const fixtureResult = <T,>(data: T): Promise<ApiResult<T>> =>
  Promise.resolve({ data, source: "fixture" });
export const rejects = () => Promise.reject(new Error("offline-7f3"));

// ---- mount -----------------------------------------------------------------------------------------

export interface SkillsRig {
  readonly m: Mounted;
  readonly el: HTMLElement;
  readonly api: Api;
  readonly clock: Clock;
  readonly navigate: Mock;
  app: AppCtx;
  /** Re-render with a changed AppCtx (same spies), as the shell does when `time` or `vw` change. */
  update(over: Partial<AppCtx>): Promise<void>;
}

export interface RigOptions {
  api?: Api;
  app?: Partial<AppCtx>;
}

export async function settle(): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await act(async () => {
      await new Promise<void>((r) => setTimeout(r, 0));
    });
  }
}

export const NIGHT: Partial<AppCtx> = { time: "night", night: true };

export async function mountSkills(opts: RigOptions = {}): Promise<SkillsRig> {
  const api = opts.api ?? skillsApi();
  const clock = fakeClock();
  const navigate = vi.fn();
  const rig: SkillsRig = {
    app: stubApp("skills", opts.app ?? {}),
    api,
    clock,
    navigate,
    m: undefined as unknown as Mounted,
    el: undefined as unknown as HTMLElement,
    update: async (over) => {
      rig.app = { ...rig.app, ...over };
      rig.m.render(tree(rig.app));
      await settle();
    },
  };
  const tree = (app: AppCtx) => (
    <ParkProvider
      api={api}
      navigate={navigate}
      schedule={clock.schedule}
      viewport={{ vw: app.vw, vh: app.vh }}
    >
      <SkillsPage app={app} />
    </ParkProvider>
  );
  const m = mount(tree(rig.app));
  Object.assign(rig, { m, el: m.container });
  await settle();
  return rig;
}

// ---- readers ---------------------------------------------------------------------------------------

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

/** A choice among a few: a button, radio or tab whose whole text is `label` (the scope and trigger pickers). */
export function choice(root: ParentNode, label: string): HTMLElement {
  const hit = qa(root, 'button, [role="radio"], [role="tab"]').find((e) => textOf(e) === label);
  if (!hit) throw new Error(`no choice labelled "${label}"`);
  return hit;
}
/** On: aria-pressed, aria-checked or aria-selected is "true". */
export const isOn = (el: Element): boolean =>
  ["aria-pressed", "aria-checked", "aria-selected"].some((a) => el.getAttribute(a) === "true");
export const isDisabled = (el: Element): boolean =>
  (el as HTMLButtonElement).disabled === true || el.getAttribute("aria-disabled") === "true";

/** The innermost element whose whole text is `text` (or matches the pattern). */
export function elWithText(root: ParentNode, text: string | RegExp): HTMLElement | undefined {
  const same = (a: string) => (typeof text === "string" ? a === text : text.test(a));
  return qa(root, "*")
    .filter((e) => same(textOf(e)))
    .pop();
}

/** A real browser click: reports whether the default action was left alone (false = prevented). */
export function clickEl(el: Element): boolean {
  let proceeded = true;
  act(() => {
    proceeded = el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
  return proceeded;
}

/** Types into a controlled input or textarea the way a browser delivers it: value set, then an input event. */
export function typeInto(field: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  act(() => {
    const proto = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement : HTMLInputElement;
    Object.getOwnPropertyDescriptor(proto.prototype, "value")?.set?.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

/** The page's `app.toast` calls, as argument lists. */
export const toasts = (app: AppCtx): unknown[][] => (app.toast as unknown as Mock).mock.calls;
/** The page's `app.go` calls, as [page, params]. */
export const goCalls = (app: AppCtx): [unknown, unknown][] =>
  (app.go as unknown as Mock).mock.calls.map((c) => [c[0], c[1]]);

// ---- the Teach wizard (STUDIO-4: three steps, Describe it, Show an example, Review the steps) ------------------

/** The wizard: the page swaps the gallery for it once "+ Teach Tilo a skill" is pressed. */
export const teachCard = (root: ParentNode): HTMLElement => q(root, '[data-testid="skills-teach"]');
export const stepBar = (root: ParentNode): HTMLElement =>
  q(teachCard(root), 'ol[aria-label="Steps"]');
/** The label of the step marked aria-current="step". */
export const currentStep = (root: ParentNode): string | undefined => {
  const marked = qa(stepBar(root), "li").filter((b) => b.getAttribute("aria-current") === "step");
  if (marked.length !== 1) return undefined;
  return STEP_LABELS.find((l) => flat(textOf(marked[0] as HTMLElement)).includes(flat(l)));
};

/** The skill name field: the first text input of the wizard step (steps 1 and 3 hold one). */
export const skillNameField = (root: ParentNode): HTMLInputElement =>
  q<HTMLInputElement>(teachCard(root), "input");
export const describeField = (root: ParentNode): HTMLTextAreaElement =>
  q<HTMLTextAreaElement>(teachCard(root), "textarea");

/** The "Ask me first" switches of Tilo's version, in plan order. */
export const askSwitches = (root: ParentNode): HTMLElement[] =>
  qa(teachCard(root), '[role="switch"]');
export const askStates = (root: ParentNode): boolean[] =>
  askSwitches(root).map((s) => s.getAttribute("aria-checked") === "true");
/** The value of one estimate ("Each run", "Time", "Stops to ask"). */
export function estimate(root: ParentNode, label: string): string | undefined {
  const k = elWithText(teachCard(root), label);
  return k?.nextElementSibling ? textOf(k.nextElementSibling) : undefined;
}

// ---- the gallery and the detail sheet ------------------------------------------------------------------

/** Opens one skill's detail sheet from its card in "All skills" and returns the sheet. */
export function openSkill(root: ParentNode, name: string): HTMLElement {
  const gallery = q(root, 'section[aria-label="All skills"]');
  const card = qa(gallery, "button").find((b) => textOf(b).includes(name));
  if (!card) throw new Error(`no skill card "${name}"`);
  clickEl(card);
  return q(root, '[role="dialog"]');
}

// ---- drivers: move the flow along ------------------------------------------------------------------

export const START = "+ Teach Tilo a skill";
export const NEXT_EXAMPLE = "Next: show an example →";
export const NEXT_REVIEW = "Next: review the steps →";

export function openTeach(rig: SkillsRig): void {
  clickEl(control(rig.el, START));
}
/** Step 1 to step 2: on the sample data the description is read at once (no timer). */
export function toExample(rig: SkillsRig): void {
  openTeach(rig);
  clickEl(control(rig.el, NEXT_EXAMPLE));
}
export function toReview(rig: SkillsRig): void {
  toExample(rig);
  clickEl(control(rig.el, NEXT_REVIEW));
}
/** Save sits on step 3, Review the steps. */
export const toSave = toReview;

export { press };

// ---- pictures: the kit's own art, to compare the page's against ---------------------------------------

const h: H = (tag, props, ...children) => createElement(tag, props, ...(children as ReactNode[]));
let held: ReturnType<typeof createKit> | null = null;
const kit = (): ReturnType<typeof createKit> => {
  held ??= createKit(h, { plans: () => ({}) });
  return held;
};

// The kit draws every agent and building as an <img> whose src is a blob URL of the SVG, a new URL per kit,
// so two renderings are compared by the SVG text behind the URL plus the img's own attributes.
async function signature(img: Element): Promise<string> {
  const src = img.getAttribute("src") ?? "";
  const svg = (await resolveObjectURL(src)?.text()) ?? src;
  return `${img.outerHTML.replace(/\ssrc="[^"]*"/, "")}|${svg}`;
}

/** The pictures under `root`, one signature each. */
export async function artIn(root: ParentNode): Promise<string[]> {
  return Promise.all(qa(root, "img").map(signature));
}

async function artOf(node: ReactNode): Promise<string> {
  const box = document.createElement("div");
  const r = createRoot(box);
  act(() => r.render(node));
  const img = box.querySelector("img");
  const sig = img ? await signature(img) : "";
  act(() => r.unmount());
  return sig;
}

/** One agent as the design's kit draws it (`K.agent(spec, size, night)`), to look for in `artIn(...)`. */
export const agentArt = (spec: AgentSpec, size: number, night = false): Promise<string> =>
  artOf(kit().agent(spec, size, night) as ReactNode);
