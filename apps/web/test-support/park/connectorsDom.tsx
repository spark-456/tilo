// WEB-11 test support: mounting and querying helpers for the Connectors page tests (happy-dom; the repo
// has no @testing-library, see componentsHarness.tsx). The page is imported when a test asks for it, so a
// test file can set its environment (the live Api) before the page module loads. Nothing here is bundled.
import { act } from "react";
import type { AppCtx } from "../../src/park/app/AppCtx";
import { type Mounted, mount } from "./componentsHarness";

/** The page inside the same `data-park` root the shell gives it (day or night). */
export async function renderPage(app: AppCtx, time: "day" | "night" = "day"): Promise<Mounted> {
  const { ConnectorsPage } = await import("../../src/park/pages/Connectors/ConnectorsPage");
  const m = mount(
    <div data-park="" data-time={time}>
      <ConnectorsPage app={app} />
    </div>,
  );
  // The page loads its data on mount; let that settle inside act so no update lands outside it.
  await flush();
  return m;
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
