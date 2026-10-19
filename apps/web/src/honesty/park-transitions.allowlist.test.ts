// WEB-MOTION-2 (PRD 9.4 HR-1 to HR-7; docs/open-questions.md BQ-WEB-3): the boot splash, the page transitions and
// the open-a-world card are UI chrome: they move because a person opened the app, clicked a tab or opened a world,
// never because an agent, a run or a decision is in some state. This pins how narrowly the honesty-scan allowlist
// may grow for them. The ticket may add AT MOST ONE entry:
//   src/park/shell/park.shell.css | css-transition
// (the splash fade, the page fade and slide, the progress bar, the card fade). The keyframes (tiloSlide, tiloSpin)
// and `animation` shorthands live in the same stylesheet and are already covered by its two existing entries, whose
// reasons must say what they now cover. Anything else (inline styles in .tsx, Element.animate, a ticker, a timer
// loop, a tween library, any file outside park/shell, any page, component or app file) is a new exception and
// needs a review of its own: it fails here on purpose.
// SECURITY REVIEW: if the builder adds the css-transition entry (or edits the two park.shell.css reasons), the
// security-reviewer should read it; it widens an honesty exemption.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ALLOWLIST, scanSource } from "../../test-support/honestyScan";
import { parseRules } from "../../test-support/park/componentsCss";
import { stripComments } from "../../test-support/park/css";

const ROOT = join(__dirname, "..", "..");
const SHELL_CSS = "src/park/shell/park.shell.css";
const read = (file: string): string => readFileSync(join(ROOT, file), "utf8");

/** The entries WEB-MOTION-1 left (src/park/shell/shell.static.test.ts pins the same list). */
const KNOWN = new Set([
  "src/world/runWorld.ts:raf",
  "src/stage/Stage.tsx:raf",
  "src/park/engines/park.ts:inline-motion-style",
  "src/park/engines/park.ts:css-animation",
  "src/park/shell/park.shell.css:css-keyframes",
  "src/park/shell/park.shell.css:css-animation",
]);
const entry = (rule: string) => ALLOWLIST.find((a) => a.file === SHELL_CSS && a.rule === rule);

describe("WEB-MOTION-2 honesty: UI-chrome motion widens the allowlist by one narrow entry at most", () => {
  it("WEB-MOTION-2 honesty: the only new allowlist entry that may exist is the shell stylesheet's css-transition, and every old entry is still there", () => {
    const keys = ALLOWLIST.map((a) => `${a.file}:${a.rule}`);
    for (const k of KNOWN) expect(keys, `${k} was removed`).toContain(k);
    const added = keys.filter((k) => !KNOWN.has(k));
    expect(
      added.filter(
        (k) =>
          k !== `${SHELL_CSS}:css-transition` &&
          k !== "src/landing/landing.motion.css:css-transition" && // LANDING-2, reviewed on its own
          !k.startsWith("src/design/tilo-t/motion.css:"), // TILO-T-FOUNDATION, reviewed on its own
      ),
      "a new exception beyond the shell stylesheet's css-transition: it needs its own review",
    ).toEqual([]);
    expect(new Set(keys).size, "an entry is listed twice").toBe(keys.length);
  });

  it("WEB-MOTION-2 honesty: if css-transition is allowed it says chrome, non-agent, transform and opacity only, and recorded events (and it is not stale)", () => {
    const e = entry("css-transition");
    if (!e) return; // the builder used keyframes only: nothing to pin
    expect(e.reason.length).toBeGreaterThanOrEqual(60);
    expect(e.reason, "says it is UI chrome").toMatch(/chrome/i);
    expect(e.reason, "says it is not an agent").toMatch(/non-agent/i);
    expect(e.reason, "says transform and opacity only").toMatch(/transform/i);
    expect(e.reason).toMatch(/opacity/i);
    expect(e.reason, "says agents animate only from recorded events (HR-1)").toMatch(/event/i);
    expect(
      scanSource(e.file, read(e.file)).some((v) => v.rule === "css-transition"),
      "the stylesheet no longer has a transition: remove the entry",
    ).toBe(true);
  });

  // MOTION3_PINS (BQ-WEB-MOTION-3a, DECIDED 8 Oct, user approved): the same single entry now also covers the
  // paint-only background-color and color fades, on the list pinned in src/park/shell/motion3.micro.css.test.ts.
  it("MOTION3_PINS honesty: the css-transition reason says background-color and color are covered, paint only, never a layout property, still no agent or run", () => {
    const e = entry("css-transition");
    expect(e, "the css-transition entry is gone").toBeDefined();
    expect(e?.reason).toMatch(/background-color/);
    expect(e?.reason).toMatch(/\bcolor\b/);
    expect(e?.reason, "says it never touches a layout property").toMatch(
      /never a layout property/i,
    );
    expect(e?.reason, "world, stage and agent motion are not covered").toMatch(
      /nothing here shows or implies an agent, a run or a decision/i,
    );
    expect(e?.reason, "reduced motion and still turn it off").toMatch(/reduced motion/i);
    expect(e?.reason).toMatch(/still/i);
  });

  it("WEB-MOTION-2 honesty: the shell stylesheet's keyframes entry names every @keyframes the file now holds", () => {
    const e = entry("css-keyframes");
    expect(e, "the css-keyframes entry is gone").toBeDefined();
    const names = [...stripComments(read(SHELL_CSS)).matchAll(/@keyframes\s+([\w-]+)/g)].map(
      (m) => m[1] as string,
    );
    expect(names.length).toBeGreaterThanOrEqual(3);
    for (const n of names) {
      expect(e?.reason, `the reason does not name @keyframes ${n}`).toContain(n);
    }
  });

  it("WEB-MOTION-2 honesty: the shell stylesheet's animation entry covers the boot splash and the loader's ring when the file animates them", () => {
    const e = entry("css-animation");
    expect(e, "the css-animation entry is gone").toBeDefined();
    const rules = parseRules(read(SHELL_CSS)).rules;
    const started = rules.filter((r) =>
      /tilo(?:Slide|Spin)/.test(r.decls.get("animation") ?? r.decls.get("animation-name") ?? ""),
    );
    // README Boot (tiloSlide) and Async actions (tiloSpin) are animations in this stylesheet: say so.
    expect(started.length, "no rule starts tiloSlide or tiloSpin").toBeGreaterThan(0);
    expect(e?.reason).toMatch(/boot|splash/i);
    expect(e?.reason).toMatch(/loader|ring|spinner/i);
    expect(e?.reason).toMatch(/non-agent|ambient|chrome/i);
    expect(e?.reason).toMatch(/event/i);
  });

  it("WEB-MOTION-2 honesty: only the shell's chrome classes start motion in the shell stylesheet (a transition or animation never sits on the city scene's layers or on a page's own classes)", () => {
    const moves = (v: string | undefined): boolean => v !== undefined && !v.startsWith("none");
    const rules = parseRules(read(SHELL_CSS)).rules.filter(
      (r) =>
        moves(r.decls.get("transition")) ||
        moves(r.decls.get("animation")) ||
        moves(r.decls.get("animation-name")),
    );
    for (const r of rules) {
      expect(r.selector, "motion on a selector outside the shell's own classes").toMatch(
        /^\[data-park\][^,]*\.park-shell__/,
      );
      expect(r.selector, "the city's layers are WEB-MOTION-1's, engine-written").not.toMatch(
        /park-shell__scene/,
      );
    }
  });
});
