import type { Page } from "@playwright/test";

/** One piece of text that does not fit: what it is, where, and how much is lost. */
export interface TextProblem {
  kind: "clipped" | "spills" | "cut" | "overlap";
  text: string;
  where: string;
  px: number;
}

/** A long title of the kind a real run gets (the owner's 21 Oct screenshot), used to stress title slots. */
export const LONG_TITLE =
  "Open wikipedia.org, search for the Eiffel Tower and summarise the history section in five short bullet points";

/**
 * Text that does not fit, read from the laid-out page:
 * - clipped: the box hides part of its own text (overflow hidden or an ellipsis or a line clamp) and has no title
 *   attribute or accessible name that carries the whole text;
 * - spills: the text runs out of its box into the space next to it;
 * - cut: an ancestor that hides overflow (not one that scrolls) cuts part of the text off;
 * - overlap: two separate pieces of text are drawn over each other.
 * Floating layers (fixed position: nav, toasts, bubble) are left out of the overlap check: they sit above the page.
 */
export function findTextProblems(page: Page, scope = "main"): Promise<TextProblem[]> {
  return page.evaluate((scope) => {
    const root = document.querySelector(scope) ?? document.body;
    const out: TextProblem[] = [];
    const label = (el: Element) =>
      `${el.tagName.toLowerCase()}.${String(el.getAttribute("class") ?? "")
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .join(".")}`;
    const ownText = (el: Element) =>
      [...el.childNodes]
        .filter((n) => n.nodeType === Node.TEXT_NODE)
        .map((n) => n.textContent ?? "")
        .join("")
        .replace(/\s+/g, " ")
        .trim();
    const hides = (v: string) => v === "hidden" || v === "clip";
    const floating = (el: Element) => {
      for (let e: Element | null = el; e; e = e.parentElement) {
        if (getComputedStyle(e).position === "fixed") return true;
      }
      return false;
    };
    const leaves: { el: HTMLElement; r: DOMRect; fixed: boolean }[] = [];
    for (const el of root.querySelectorAll<HTMLElement>("*")) {
      const text = ownText(el);
      if (text.length < 2) continue;
      if (el.closest('svg, canvas, [aria-hidden="true"], .park-sr-only, .park-home-sr, [hidden]'))
        continue;
      // Inside a visually hidden block (screen-reader text: a 1px box clipped to nothing).
      let hiddenBlock = false;
      for (let a: Element | null = el; a && a !== document.body; a = a.parentElement) {
        const acs = getComputedStyle(a);
        if (acs.clipPath.includes("inset(50%)") || acs.clip.startsWith("rect(0"))
          hiddenBlock = true;
      }
      if (hiddenBlock) continue;
      if (
        !el.checkVisibility({
          visibilityProperty: true,
          opacityProperty: true,
        } as CheckVisibilityOptions)
      )
        continue;
      const cs = getComputedStyle(el);
      if (cs.position === "absolute" && (cs.clip !== "auto" || cs.clipPath.includes("inset(50%)")))
        continue;
      // The text itself, not its box: a padded paragraph a few pixels wider than its card loses no letters.
      const range = document.createRange();
      range.selectNodeContents(el);
      const r = range.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) continue;
      // An element 1px wide or high with hidden overflow is a screen-reader-only text: skip it.
      if (r.width <= 1 || r.height <= 1) continue;
      // The shell gives cut text a title when the pointer rests on it (truncationTitles.ts): hover it first.
      if ((cs.textOverflow === "ellipsis" || cs.webkitLineClamp !== "none") && !el.title)
        el.dispatchEvent(new PointerEvent("pointerover", { bubbles: true }));
      const named = Boolean(el.title || el.closest("[title]") || el.getAttribute("aria-label"));
      const where = label(el);
      const snippet = text.slice(0, 60);
      const overflowX = el.scrollWidth - el.clientWidth;
      const overflowY = el.scrollHeight - el.clientHeight;
      const clamp = cs.webkitLineClamp !== "none" && cs.webkitLineClamp !== "";
      if ((hides(cs.overflowX) || cs.textOverflow === "ellipsis") && overflowX > 1 && !named) {
        out.push({ kind: "clipped", text: snippet, where, px: overflowX });
      } else if (clamp && overflowY > 1 && !named) {
        out.push({ kind: "clipped", text: snippet, where, px: overflowY });
      } else if (
        !hides(cs.overflowX) &&
        overflowX > 2 &&
        cs.whiteSpace !== "normal" &&
        el.clientWidth > 0
      ) {
        out.push({ kind: "spills", text: snippet, where, px: overflowX });
      }
      // An ancestor that hides (not scrolls) overflow and cuts this text.
      for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
        const as = getComputedStyle(a);
        // Text inside a box that scrolls can be scrolled into view: its edge is not a cut.
        if (/auto|scroll/.test(as.overflowX + as.overflowY)) break;
        const clipsX = hides(as.overflowX);
        const clipsY = hides(as.overflowY);
        if (!clipsX && !clipsY) continue;
        const ar = a.getBoundingClientRect();
        const cutX = clipsX ? Math.max(0, r.right - ar.right, ar.left - r.left) : 0;
        const cutY = clipsY ? Math.max(0, r.bottom - ar.bottom, ar.top - r.top) : 0;
        // A cut wider than the text itself means it is scrolled out of a carousel or a closed panel: not a cut.
        if ((cutX > 2 && cutX < r.width) || (cutY > 2 && cutY < r.height)) {
          if (!named)
            out.push({
              kind: "cut",
              text: snippet,
              where: `${where} in ${label(a)}`,
              px: Math.round(Math.max(cutX, cutY)),
            });
        }
        break;
      }
      // What is left of the text once every clipping parent has cut it (a calendar hides its late hours).
      let vis = { l: r.left, t: r.top, r: r.right, b: r.bottom };
      // From the element itself: a clamped or ellipsed text hides its own overflow too.
      for (let a: Element | null = el; a && a !== document.body; a = a.parentElement) {
        const as = getComputedStyle(a);
        if (as.overflowX === "visible" && as.overflowY === "visible") continue;
        const ar = a.getBoundingClientRect();
        vis = {
          l: Math.max(vis.l, ar.left),
          t: Math.max(vis.t, ar.top),
          r: Math.min(vis.r, ar.right),
          b: Math.min(vis.b, ar.bottom),
        };
      }
      if (vis.r - vis.l < 2 || vis.b - vis.t < 2) continue;
      leaves.push({
        el,
        r: new DOMRect(vis.l, vis.t, vis.r - vis.l, vis.b - vis.t),
        fixed: floating(el),
      });
    }
    const flow = leaves.filter((l) => !l.fixed);
    for (let i = 0; i < flow.length; i++) {
      const a = flow[i];
      if (!a) continue;
      for (let j = i + 1; j < flow.length; j++) {
        const b = flow[j];
        if (!b || a.el.contains(b.el) || b.el.contains(a.el)) continue;
        const w = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
        const h = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
        if (w <= 2 || h <= 2) continue;
        // Line boxes of inline text can touch by a pixel or two; a real overlap covers a good part of a glyph row.
        const small = Math.min(a.r.width * a.r.height, b.r.width * b.r.height);
        if ((w * h) / small < 0.25) continue;
        out.push({
          kind: "overlap",
          text: `${ownText(a.el).slice(0, 30)} / ${ownText(b.el).slice(0, 30)}`,
          where: `${label(a.el)} / ${label(b.el)}`,
          px: Math.round(h),
        });
      }
    }
    return out;
  }, scope);
}

/**
 * Puts LONG_TITLE into every title slot in the page (headings and elements whose class names a title or a name, with
 * only text inside), as a real run's long name would. React is not told: the page is measured right after.
 */
export function stretchTitles(page: Page, scope = "main"): Promise<number> {
  return page.evaluate(
    ({ scope, long }) => {
      const root = document.querySelector(scope) ?? document.body;
      let n = 0;
      for (const el of root.querySelectorAll<HTMLElement>(
        'h1, h2, h3, [class*="title" i], [class*="name" i]',
      )) {
        if (el.children.length > 0 || (el.textContent ?? "").trim().length < 3) continue;
        if (el.closest('svg, [aria-hidden="true"], input, textarea, select, option')) continue;
        el.textContent = long;
        n++;
      }
      return n;
    },
    { scope, long: LONG_TITLE },
  );
}
