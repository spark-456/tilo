// WEB-2 test support: a tiny React mount for happy-dom (the repo has no @testing-library), plus the
// keyboard helper that stands in for the browser's own button activation. Nothing here is bundled.
import { type ReactElement, act } from "react";
import { type Root, createRoot } from "react-dom/client";

Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);

export interface Mounted {
  readonly container: HTMLElement;
  render(ui: ReactElement): void;
  unmount(): void;
}

const live: Mounted[] = [];

export function mount(ui: ReactElement): Mounted {
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

/** Call from afterEach in every test file that mounts. */
export function cleanup(): void {
  for (const m of live.splice(0)) m.unmount();
  document.body.innerHTML = "";
}

export function click(el: Element): void {
  act(() => {
    (el as HTMLElement).click();
  });
}

/** A click event dispatched straight at the element (a disabled control must ignore it too). */
export function dispatchClick(el: Element): void {
  act(() => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
}

export function focus(el: Element): void {
  act(() => {
    (el as HTMLElement).focus();
  });
}

function nativeActivates(el: Element): el is HTMLButtonElement {
  return el instanceof HTMLButtonElement && !el.disabled;
}

/**
 * A key press the way a browser delivers it: keydown, then (for a native button) the click that Enter
 * fires on keydown and Space fires on keyup, unless the page prevented the default. A custom control
 * (role="button" on a div) gets no click from the browser, so its own onKeyDown must do the work.
 */
export function press(el: Element, key: string): void {
  act(() => {
    const down = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
    el.dispatchEvent(down);
    if (key === "Enter" && !down.defaultPrevented && nativeActivates(el)) el.click();
    if (key === " ") {
      const up = new KeyboardEvent("keyup", { key, bubbles: true, cancelable: true });
      el.dispatchEvent(up);
      if (!down.defaultPrevented && !up.defaultPrevented && nativeActivates(el)) el.click();
    }
  });
}

/** A key delivered at the document itself (nothing focused inside the component). */
export function pressDocument(key: string): void {
  act(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
}

export function active(): Element | null {
  return document.activeElement;
}

export const q = <T extends Element = HTMLElement>(root: ParentNode, sel: string): T => {
  const el = root.querySelector<T>(sel);
  if (!el) throw new Error(`no element matches ${sel}`);
  return el;
};

export const qa = <T extends Element = HTMLElement>(root: ParentNode, sel: string): T[] => [
  ...root.querySelectorAll<T>(sel),
];

/** UX-1: how many filled primary buttons sit under `root`. A demo panel or a page allows exactly one. */
export function countPrimary(root: ParentNode): number {
  return root.querySelectorAll("button.park-btn--primary").length;
}

/** The accessible name the tests rely on: aria-label, else the text. */
export function nameOf(el: Element): string {
  return (el.getAttribute("aria-label") ?? el.textContent ?? "").trim();
}
