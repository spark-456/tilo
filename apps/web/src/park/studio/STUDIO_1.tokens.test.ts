// UI-STUDIO-1: the Studio role tokens (config/themes/studio.json) are a real light and a real dark theme, both pass
// WCAG 2.2 AA for the text pairs the app draws, the stylesheets stay still (HR-1..7: no transition, animation or
// keyframes) and every Studio rule is scoped to the Studio theme, so the Metropolis theme keeps the Park look.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { readThemes } from "../../../scripts/generate-themes.mjs";
import { parseRules } from "../../../test-support/park/componentsCss";
import { stripComments } from "../../../test-support/park/css";

const studio = readThemes().find((t: { id: string }) => t.id === "studio") as {
  day: Record<string, string>;
  night: Record<string, string>;
};

const channel = (v: number): number => {
  const c = v / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
const lum = (hex: string): number => {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (!m) throw new Error(`not a plain hex colour: ${hex}`);
  const [r, g, b] = [m[1], m[2], m[3]].map((x) => channel(Number.parseInt(x as string, 16)));
  return 0.2126 * (r as number) + 0.7152 * (g as number) + 0.0722 * (b as number);
};
const contrast = (a: string, b: string): number => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
};

// [text, background] pairs the shell, the components and the pages draw (role names of park.css and studio.json).
const TEXT_PAIRS: readonly [string, string][] = [
  ["ink", "paper"],
  ["ink", "card"],
  ["ink2", "card"],
  ["ink2", "paper"],
  ["ink3", "paper"],
  ["ink3", "card"],
  ["ink3", "sunk"],
  ["heroInk", "heroSoft"],
  ["heroInk", "card"],
  ["onPri", "priFill"],
  ["toastInk", "toast"],
  ["okInk", "okSoft"],
  ["amberInk", "amberSoft"],
  ["amberInk", "amberTile"],
  ["redInk", "redSoft"],
  ["redInk", "card"],
  ["blueInk", "blueSoft"],
  ["lilacInk", "lilacSoft"],
  ["sch", "schSoft"],
];

describe("UI-STUDIO-1 tokens: Studio light and Studio dark", () => {
  it("STUDIO_1 day and night define the same roles (dark is a whole theme, not a filter)", () => {
    expect(Object.keys(studio.night).sort()).toEqual(Object.keys(studio.day).sort());
    expect(studio.day.paper).not.toBe(studio.night.paper);
    expect(studio.day.ink).not.toBe(studio.night.ink);
    const css = fs.readFileSync(path.join(__dirname, "studio.css"), "utf8");
    expect(stripComments(css)).not.toMatch(/filter\s*:\s*invert/);
  });

  it("STUDIO_1 the lime is the design's and is never text on white: the dark lime ink is", () => {
    expect(studio.day.lime?.toUpperCase()).toBe("#C8F23A");
    expect(studio.night.priFill?.toUpperCase()).toBe("#C8F23A");
    expect(contrast(studio.day.lime as string, "#FFFFFF")).toBeLessThan(3); // why lime is a fill only
    expect(contrast(studio.day.heroInk as string, "#FFFFFF")).toBeGreaterThanOrEqual(4.5);
  });

  for (const mode of ["day", "night"] as const) {
    it(`STUDIO_1 every text pair passes WCAG 2.2 AA 4.5:1 by ${mode}`, () => {
      const t = studio[mode];
      for (const [fg, bg] of TEXT_PAIRS) {
        const ratio = contrast(t[fg] as string, t[bg] as string);
        expect(ratio, `${mode} ${fg} on ${bg}: ${ratio.toFixed(2)}`).toBeGreaterThanOrEqual(4.5);
      }
      // the pages' white text on the hero fill, and the theme's own ok and red as text on a card
      expect(
        contrast("#FFFFFF", t.heroFill as string),
        `${mode} white on heroFill`,
      ).toBeGreaterThanOrEqual(4.5);
      expect(
        contrast(t.ok as string, t.card as string),
        `${mode} ok on card`,
      ).toBeGreaterThanOrEqual(4.5);
      expect(
        contrast(t.red as string, t.card as string),
        `${mode} red on card`,
      ).toBeGreaterThanOrEqual(4.5);
      // the lime is a fill with ink text (#0B0B0C) in both themes: the toast action, the logo mark by night
      expect(contrast("#0B0B0C", t.lime as string), `${mode} ink on lime`).toBeGreaterThanOrEqual(
        4.5,
      );
      // the focus ring and the toast's check mark are graphics: 3:1
      expect(contrast(t.focus as string, t.paper as string)).toBeGreaterThanOrEqual(3);
      expect(contrast(t.inv as string, t.ok as string)).toBeGreaterThanOrEqual(3);
    });
  }
});

describe("UI-STUDIO-1 stylesheets: scoped and still", () => {
  const read = (f: string) => fs.readFileSync(path.join(__dirname, f), "utf8");

  it("STUDIO_1 no transition, animation, keyframes or smooth scroll in the Studio stylesheets", () => {
    for (const f of ["studio.css", "studio.components.css"]) {
      const body = stripComments(read(f));
      expect(body, f).not.toMatch(/@keyframes/i);
      expect(body, f).not.toMatch(/(?:^|[\s{;])(?:transition|animation)(?:-[a-z-]+)?\s*:/im);
      expect(body, f).not.toMatch(/scroll-behavior\s*:\s*smooth/);
      expect(body, f).not.toMatch(/\bwill-change\b/);
    }
  });

  it("STUDIO_1 every studio.css rule is scoped to the Studio theme root", () => {
    const { rules } = parseRules(read("studio.css"));
    expect(rules.length).toBeGreaterThan(40);
    const unscoped = rules
      .flatMap((r) => r.selector.split(/,(?![^(]*\))/).map((s) => s.trim()))
      .filter(
        (s) =>
          !s.startsWith('[data-park][data-theme="studio"]') &&
          !s.startsWith(':where([data-park][data-theme="studio"])'),
      );
    expect(unscoped).toEqual([]);
  });

  it("STUDIO_1 every studio.components.css rule sits under [data-park]", () => {
    const { rules } = parseRules(read("studio.components.css"));
    expect(rules.map((r) => r.selector).filter((s) => !s.startsWith("[data-park]"))).toEqual([]);
  });

  it("STUDIO_1 the Park root loads the Studio fonts and stylesheet after the theme tokens", () => {
    const app = fs.readFileSync(path.join(__dirname, "..", "app", "ParkApp.tsx"), "utf8");
    const at = (s: string) => app.indexOf(s);
    expect(at('import "../tokens/themes.css";')).toBeGreaterThan(-1);
    expect(at('import "../studio/studio.css";')).toBeGreaterThan(
      at('import "../tokens/themes.css";'),
    );
    expect(at('import "../studio/fonts";')).toBeGreaterThan(-1);
  });
});
