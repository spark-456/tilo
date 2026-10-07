// WEB-3b: the one stylesheet of the shell, apps/web/src/park/shell/park.shell.css (plan section 10: one
// stylesheet per area, every selector under [data-park]; plan 8d: the shell shipped a STATIC city, so no
// transition, animation or keyframes; WEB-MOTION-1 (BQ-WEB-3) restored the city's cars and walkers with their
// own honesty-scan entries, so only their keyframes and a pause rule are allowed now).
// The sizes, radii and colours are not read from the file: they are measured on the running page against the
// reference in e2e/park-shell-visual.spec.ts.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseRules } from "../../../test-support/park/componentsCss";
import { stripComments } from "../../../test-support/park/css";

const css = (): string => fs.readFileSync(path.join(__dirname, "park.shell.css"), "utf8");

describe("WEB_3b_css: park.shell.css", () => {
  it("WEB_3b_css_every_selector_sits_under_data_park", () => {
    const rules = parseRules(css()).rules;
    expect(rules.length).toBeGreaterThan(10);
    expect(rules.map((r) => r.selector).filter((s) => !s.startsWith("[data-park]"))).toEqual([]);
  });

  it("WEB_3b_css_motion_is_the_city_movers_and_the_shell_chrome_keyframes_only", () => {
    // WEB-MOTION-1: the city's cars and walkers are keyframes plus one pause rule.
    // Updated for WEB-MOTION-2: the shell's own chrome (splash, page swap, bar, world card) adds transitions on
    // transform and opacity (pinned in motion.transitions.css.test.ts) and the keyframes tiloSlide, tiloSpin,
    // tiloFade; every animation declaration is the pause, "none" (reduced motion) or one of those.
    const text = stripComments(css());
    for (const d of text.match(/\banimation(?:-[a-z-]+)?\s*:[^;]*;/gi) ?? []) {
      expect(d).toMatch(/^animation-play-state:|:\s*none\b|\btilo(?:Slide|Spin|Fade)\b/i);
    }
    expect(parseRules(css()).others.map((o) => o.head)).toEqual([
      "@keyframes mvXY",
      "@keyframes waddle",
      "@keyframes walkFrame",
      "@keyframes tiloSlide",
      "@keyframes tiloSpin",
      "@keyframes tiloFade",
    ]);
    // Compositor-only: a keyframe changes transform or opacity and nothing else.
    const props = [...text.matchAll(/@keyframes[^{]+\{([\s\S]*?\n\})/g)]
      .flatMap((m) => [...(m[1] ?? "").matchAll(/([a-z-]+)\s*:/g)].map((x) => x[1]))
      .filter((p, i, all) => all.indexOf(p) === i)
      .sort();
    expect(props).toEqual(["opacity", "transform"]);
  });

  it("WEB_3b_css_glass_blur_is_limited_to_the_nav", () => {
    // README Performance: glass blur only on the nav and the Home panels, so inner pages stay solid.
    const blurs = parseRules(css()).rules.filter((r) => r.decls.has("backdrop-filter"));
    expect(blurs.length).toBeLessThanOrEqual(1);
  });
});
