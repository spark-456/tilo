// UI-10 / A6 (14 Oct QA, Home at night): the Home sample strip floats over the lit city, so its surface must be
// opaque. The rule is read from sample.css and the two token values from tokens/park.css; the contrast of the
// strip's text (--ink2) on its surface (--pop) is computed for day and night. The rendered colours are checked
// in a browser by e2e/park-sample-strip-a6.spec.ts.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const sample = readFileSync(join(__dirname, "sample.css"), "utf8");
const tokens = readFileSync(join(__dirname, "..", "tokens", "park.css"), "utf8");

const block = (src: string, opener: string): string => {
  const start = src.indexOf(opener);
  if (start < 0) throw new Error(`no ${opener}`);
  return src.slice(start, src.indexOf("}", start));
};
const hex = (src: string, name: string): [number, number, number] => {
  const m = new RegExp(`${name}:\s*#([0-9A-Fa-f]{6})`).exec(src);
  if (!m?.[1]) throw new Error(`no ${name}`);
  const n = Number.parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const lum = ([r, g, b]: [number, number, number]): number => {
  const c = [r, g, b].map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a: [number, number, number], b: [number, number, number]): number => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
};

describe("UI_10_A6_sample_strip_on_home", () => {
  it("UI_10_A6_the_home_strip_surface_is_the_opaque_popover_token", () => {
    const rules = [
      ...sample.matchAll(/\[data-park\] \.park-first-run-banner--home \{[^}]*\}/g),
    ].map((m) => m[0]);
    expect(rules.some((r) => /background:\s*var\(--pop\)/.test(r))).toBe(true);
    expect(rules.join("")).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(/);
  });

  it("UI_10_A6_pop_is_a_solid_colour_in_both_themes", () => {
    const day = block(tokens, "[data-park] {");
    const night = block(tokens, '[data-park][data-time="night"] {');
    expect(day).toMatch(/--pop:\s*#[0-9A-Fa-f]{6}/);
    expect(night).toMatch(/--pop:\s*#[0-9A-Fa-f]{6}/);
  });

  it.each([
    ["day", "[data-park] {"],
    ["night", '[data-park][data-time="night"] {'],
  ])("UI_10_A6_text_on_the_strip_is_at_least_4.5_to_1_at_%s", (_name, opener) => {
    const t = block(tokens, opener);
    expect(ratio(hex(t, "--ink2"), hex(t, "--pop"))).toBeGreaterThanOrEqual(4.5);
  });
});
