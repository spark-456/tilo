// WEB-MOTION-2 (boot splash, page transitions, open-a-world steps): the stylesheet of the shell,
// apps/web/src/park/shell/park.shell.css, read as text. Pinned to design_handoff_tilo_web_app/README.md
// "Interactions and motion" and "Performance", and to the keyframes of the reference
// (design_handoff_tilo_web_app/design/Tilo App.dc.html): tiloSlide (the boot bar), tiloSpin (the loader's ring).
//
// What the running page does with these rules (durations, easings, the bar's 35/78/100 steps, reduced motion)
// is measured in a real browser in e2e/park-motion-transitions.spec.ts; this file pins what a stylesheet can
// be held to without a browser: the keyframes, the compositor-only budget (transform and opacity, nothing that
// lays out or repaints), and that no glass blur sits on anything that moves.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  type CssRule,
  parseRules,
  readComponentsCss,
} from "../../../test-support/park/componentsCss";
import { stripComments } from "../../../test-support/park/css";

const css = (): string => fs.readFileSync(path.join(__dirname, "park.shell.css"), "utf8");

/** The body of `@keyframes <name>`, or null. */
function keyframes(text: string, name: string): string | null {
  const m = new RegExp(`@keyframes\\s+${name}\\s*\\{`).exec(text);
  if (!m) return null;
  let depth = 1;
  let i = m.index + m[0].length;
  const from = i;
  while (i < text.length && depth > 0) {
    if (text[i] === "{") depth++;
    else if (text[i] === "}") depth--;
    i++;
  }
  return text.slice(from, i - 1);
}

/** Every declaration of every rule whose value mentions `needle` in an animation property, joined. */
function animationOf(
  rules: readonly CssRule[],
  needle: string,
): { selector: string; value: string }[] {
  const props = [
    "animation",
    "animation-name",
    "animation-duration",
    "animation-timing-function",
    "animation-iteration-count",
  ];
  return rules
    .filter((r) =>
      (r.decls.get("animation") ?? r.decls.get("animation-name") ?? "").includes(needle),
    )
    .map((r) => ({
      selector: r.selector,
      value: props
        .map((p) => r.decls.get(p) ?? "")
        .join(" ")
        .toLowerCase(),
    }));
}

describe("WEB-MOTION-2 css: the boot splash's bar and the loader's ring use the reference keyframes", () => {
  it("WEB-MOTION-2 css: @keyframes tiloSlide runs translateX(-110%) to translateX(260%) (README Boot: the sliding bar)", () => {
    const body = keyframes(stripComments(css()), "tiloSlide");
    expect(body, "park.shell.css has no @keyframes tiloSlide").not.toBeNull();
    expect(body).toMatch(/-110%/);
    expect(body).toMatch(/260%/);
    expect(body).toMatch(/translateX/);
  });

  it("WEB-MOTION-2 css: the splash's bar runs tiloSlide for 1.1s on cubic-bezier(.4,0,.2,1), forever (README Boot: tiloSlide 1.1s)", () => {
    const hits = animationOf(parseRules(css()).rules, "tiloSlide");
    expect(hits.length, "no rule animates with tiloSlide").toBeGreaterThan(0);
    for (const h of hits) {
      expect(h.selector, "the slide belongs to the boot splash").toMatch(/park-shell__boot/);
      expect(h.value).toMatch(/(?:^|[\s,])1\.1s|1100ms/);
      expect(h.value).toMatch(/cubic-bezier\(\s*0?\.4\s*,\s*0\s*,\s*0?\.2\s*,\s*1\s*\)/);
      expect(h.value).toMatch(/infinite/);
    }
  });

  it("WEB-MOTION-2 css: @keyframes tiloSpin is a full turn: to { transform: rotate(360deg) } (README Async actions)", () => {
    const body = keyframes(stripComments(css()), "tiloSpin");
    expect(body, "park.shell.css has no @keyframes tiloSpin").not.toBeNull();
    expect(body).toMatch(/rotate\(\s*360deg\s*\)/);
  });

  it("WEB-MOTION-2 css: the loader's ring spins with tiloSpin .7s linear, forever (README Async actions: tiloSpin .7s)", () => {
    const hits = animationOf(parseRules(css()).rules, "tiloSpin");
    expect(hits.length, "no rule animates with tiloSpin").toBeGreaterThan(0);
    for (const h of hits) {
      expect(h.selector, "the spin belongs to the loader's ring").toMatch(/park-shell__ring/);
      expect(h.value).toMatch(/(?:^|[\s,])0?\.7s|700ms/);
      expect(h.value).toMatch(/linear/);
      expect(h.value).toMatch(/infinite/);
    }
  });
});

describe("WEB-MOTION-2 css: compositor only (transform and opacity), no glass blur on anything that moves", () => {
  it("WEB-MOTION-2 css: every @keyframes in the shell changes transform or opacity and nothing else", () => {
    const text = stripComments(css());
    const names = [...text.matchAll(/@keyframes\s+([\w-]+)/g)].map((m) => m[1] as string);
    expect(names).toEqual(expect.arrayContaining(["mvXY", "waddle", "walkFrame"]));
    for (const name of names) {
      const body = keyframes(text, name) ?? "";
      const props = [...body.matchAll(/([a-z-]+)\s*:/g)].map((x) => x[1] as string);
      for (const p of props) {
        expect(["transform", "opacity"], `@keyframes ${name} changes ${p}`).toContain(p);
      }
    }
  });

  it("WEB-MOTION-2 css: every transition in the shell names transform and/or opacity only (a progress bar may scaleX; it never animates width)", () => {
    const names: string[] = [];
    for (const r of parseRules(css()).rules) {
      const shorthand = r.decls.get("transition");
      if (shorthand !== undefined && !/^none\b/.test(shorthand)) {
        // Top-level commas split the list; the property is the one token that is not a time or a curve.
        let depth = 0;
        let cur = "";
        const items: string[] = [];
        for (const ch of shorthand) {
          if (ch === "(") depth++;
          if (ch === ")") depth--;
          if (ch === "," && depth === 0) {
            items.push(cur);
            cur = "";
          } else cur += ch;
        }
        items.push(cur);
        for (const item of items) {
          const prop = item
            .replace(/cubic-bezier\([^)]*\)|steps\([^)]*\)/g, " ")
            .split(/\s+/)
            .find(
              (t) =>
                t !== "" &&
                !/^-?[\d.]+m?s$/.test(t) &&
                !/^(ease|ease-in|ease-out|ease-in-out|linear|step-start|step-end|allow-discrete|normal)$/.test(
                  t,
                ),
            );
          names.push(`${r.selector}: ${prop ?? "all"}`);
        }
      }
      const longhand = r.decls.get("transition-property");
      if (longhand !== undefined && !/^none\b/.test(longhand)) {
        for (const p of longhand.split(",")) names.push(`${r.selector}: ${p.trim()}`);
      }
    }
    const bad = names.filter((n) => !/: (transform|opacity)$/.test(n));
    expect(bad, "a transition on anything else lays out or repaints on every frame").toEqual([]);
  });

  it("WEB-MOTION-2 css: backdrop-filter is on the nav and nowhere else in the shell or the shared components (the scrim, the splash and the page fade)", () => {
    const blurred = parseRules(css()).rules.filter(
      (r) => r.decls.has("backdrop-filter") || r.decls.has("-webkit-backdrop-filter"),
    );
    for (const r of blurred) expect(r.selector).toMatch(/park-shell__nav/);
    const shared = parseRules(readComponentsCss()).rules.filter(
      (r) => r.decls.has("backdrop-filter") || r.decls.has("-webkit-backdrop-filter"),
    );
    expect(
      shared.map((r) => r.selector),
      "the loader's scrim fades: a blur under it would repaint the page on every frame",
    ).toEqual([]);
  });
});
