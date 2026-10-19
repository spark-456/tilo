// ONBOARD-1: keeps Tab inside an onboarding dialog (the coach mark sits at the end of the page, so Tab from its last
// control would otherwise leave the document).
import type { KeyboardEvent } from "react";

const FOCUSABLE =
  "button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex='-1'])";

export function trapTab(e: KeyboardEvent<HTMLElement>): void {
  if (e.key !== "Tab") return;
  const root = e.currentTarget;
  const items = [...root.querySelectorAll<HTMLElement>(FOCUSABLE)];
  const first = items[0];
  const last = items[items.length - 1];
  if (!first || !last) return;
  const at = document.activeElement;
  if (e.shiftKey && (at === first || at === root)) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && at === last) {
    e.preventDefault();
    first.focus();
  }
}
