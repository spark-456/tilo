// SPEND-CAPS-FEEDBACK test support: the exact words and the small DOM readers every lifetime-cap test shares.
// The copy is the user's request of 8 Oct 2026 (not in the PRD): the person has used their beta allowance; new plans
// and subscriptions come after beta testing ends; if they liked Tilo they can help with honest feedback and critique.
// The sentences are also in services/api/tests/API_SPEND_FEEDBACK.md for the builder. Nothing here is bundled.
import { act } from "react";

export const COPY = {
  title: "Beta allowance used",
  allowance: "You have used your beta allowance for live models.",
  later: "New plans and subscriptions come after beta testing ends.",
  ask: "If you liked Tilo, you can help by giving honest feedback and critique.",
  label: "Your feedback",
  send: "Send feedback",
  sending: "Sending…",
  close: "Close",
  thanks: "Thanks. Your feedback was received.",
  failed: "Your feedback was not sent. Your text is still here, so you can try again.",
} as const;

/** The server's `detail` for the lifetime cap (services/api/src/tilo_api/spend.py CAP_REACHED). Never shown. */
export const SERVER_CAP_SENTENCE =
  "You have reached the lifetime spending cap for live models, so new work is refused for now.";
export const CAP_BODY = { detail: SERVER_CAP_SENTENCE, code: "spend_cap_reached" } as const;
export const MAX_FEEDBACK_CHARS = 2000;

export const squash = (s: string | null | undefined): string =>
  (s ?? "").replace(/\s+/g, " ").trim();

export const dialogIn = (root: ParentNode): HTMLElement | null =>
  root.querySelector<HTMLElement>('[role="dialog"]');
export const areaIn = (root: ParentNode): HTMLTextAreaElement | null =>
  root.querySelector<HTMLTextAreaElement>("textarea");
export const buttonNamed = (root: ParentNode, name: string | RegExp): HTMLButtonElement | null =>
  [...root.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
    typeof name === "string"
      ? squash(b.textContent) === name || b.getAttribute("aria-label") === name
      : name.test(squash(b.textContent)) || name.test(b.getAttribute("aria-label") ?? ""),
  ) ?? null;

/** An element's accessible name: aria-labelledby, aria-label, a `label[for]`, or a wrapping label. */
export function nameOf(el: HTMLElement): string {
  const ids = el.getAttribute("aria-labelledby");
  if (ids) {
    return squash(
      ids
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.textContent ?? "")
        .join(" "),
    );
  }
  const own = el.getAttribute("aria-label");
  if (own) return squash(own);
  if (el.id) {
    const label = document.querySelector(`label[for="${el.id}"]`);
    if (label) return squash(label.textContent);
  }
  return squash(el.closest("label")?.textContent);
}

/** Types into a controlled textarea the way a browser delivers it: value set, then an input event. */
export function typeFeedback(area: HTMLTextAreaElement, value: string): void {
  act(() => {
    const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
    set?.call(area, value);
    area.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

export function clickButton(button: HTMLElement): void {
  act(() => {
    button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
}

export function pressKey(el: Element, key: string): void {
  act(() => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
}

/** Lets resolved and rejected promises, and the renders they cause, run. */
export async function flush(): Promise<void> {
  for (let i = 0; i < 4; i++) {
    await act(async () => {
      await new Promise<void>((r) => setTimeout(r, 0));
    });
  }
}

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
