// UX-SMOOTH (owner, 21 Oct: "texts bleeding"): a piece of text the layout cuts short with an ellipsis or a line clamp
// shows its whole wording as a tooltip when the pointer rests on it. One document listener covers every page, so a
// long run name in a card, a row or a chip is never lost. It sets `title` only where none was given, and takes back
// a title it set once the text fits again (a wider window).
import { useEffect } from "react";

const MAX_TITLE = 300;
const MINE = "autoTitle";

/** The whole text of `el` when the layout shows only part of it (ellipsis or line clamp), else null. */
export function cutText(el: HTMLElement): string | null {
  const cs = getComputedStyle(el);
  const clamp = cs.webkitLineClamp !== "" && cs.webkitLineClamp !== "none";
  if (cs.textOverflow !== "ellipsis" && !clamp) return null;
  const cut =
    el.scrollWidth > el.clientWidth + 1 || (clamp && el.scrollHeight > el.clientHeight + 1);
  if (!cut) return null;
  const text = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
  return text ? text.slice(0, MAX_TITLE) : null;
}

/** Gives the cut text under `target` (or one of its three nearest parents) its whole wording as a title. */
export function titleCutText(target: EventTarget | null): void {
  let el = target instanceof Element ? target : null;
  for (let depth = 0; el && depth < 4; depth++, el = el.parentElement) {
    if (!(el instanceof HTMLElement)) continue;
    const own = el.dataset[MINE] === "1";
    if (el.hasAttribute("title") && !own) return; // the page named it itself
    const text = cutText(el);
    if (text) {
      el.title = text;
      el.dataset[MINE] = "1";
      return;
    }
    if (own) {
      el.removeAttribute("title");
      delete el.dataset[MINE];
    }
  }
}

/** Installs the listener for as long as the shell is mounted. */
export function useTruncationTitles(): void {
  useEffect(() => {
    const over = (e: Event) => titleCutText(e.target);
    document.addEventListener("pointerover", over, { passive: true });
    document.addEventListener("focusin", over);
    return () => {
      document.removeEventListener("pointerover", over);
      document.removeEventListener("focusin", over);
    };
  }, []);
}
