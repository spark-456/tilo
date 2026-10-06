// WEB-10 test helper (not a test): settle, DOM queries and actions the Team tests share. No timers: async
// work is flushed with microtasks. The repo has no @testing-library; roles and names are read from attributes.
// The page folder is read as park code by park.static.test.ts, so this file imports nothing from outside park;
// mounting, the AppCtx stub and the Api spies are in test-support/park/teamHarness.ts.
import { act } from "react";

/** Let promises, effects and the state updates they cause finish (microtasks only). */
export async function settle(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 30; i++) await Promise.resolve();
  });
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
