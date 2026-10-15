// FR-WLD-15 (PRD 6.4, 18.2): themes come from config/themes/ with Metropolis as the default; a second theme loads
// with no code change; day and night both keep working.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  CSS_PATH,
  THEMES_DIR,
  TS_PATH,
  generate,
  parseTheme,
  readThemes,
} from "../../../scripts/generate-themes.mjs";
import { DEFAULT_THEME, THEMES, themeFor } from "./themes";

const rgb = (c: string): number[] => {
  const hex = /^#([0-9a-f]{6})$/i.exec(c);
  if (hex) return [0, 2, 4].map((i) => Number.parseInt((hex[1] as string).slice(i, i + 2), 16));
  return (c.match(/\d+/g) ?? []).slice(0, 3).map(Number);
};

function tempThemes(extra: Record<string, unknown>): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tilo-themes-"));
  for (const f of fs.readdirSync(THEMES_DIR))
    fs.copyFileSync(path.join(THEMES_DIR, f), path.join(dir, f));
  for (const [name, body] of Object.entries(extra)) {
    fs.writeFileSync(path.join(dir, name), typeof body === "string" ? body : JSON.stringify(body));
  }
  return dir;
}

const harbour = {
  id: "harbour",
  name: "Harbour",
  default: false,
  day: { ground: "#c8c8c8", hero: "#444444" },
  night: { ground: "#303030", hero: "#999999" },
};

describe("FR-WLD-15 themes from config/themes", () => {
  // Updated for UI-STUDIO-1: Studio is the default theme; Metropolis stays first as the base park.css.
  it("FR-WLD-15 loads Studio as the default, Metropolis as the base and a second theme from the config folder", () => {
    const themes = readThemes(THEMES_DIR);
    expect(themes[0]).toMatchObject({ id: "metropolis", isDefault: false });
    expect(themes.filter((t) => t.isDefault).map((t) => t.id)).toEqual(["studio"]);
    expect(themes.map((t) => t.id)).toContain("neutral");
    expect(DEFAULT_THEME).toBe("studio");
    expect(THEMES.map((t) => t.id)).toEqual(themes.map((t) => t.id));
    expect(themeFor("neutral")).toBe("neutral");
    expect(themeFor("metropolis")).toBe("metropolis");
    for (const bad of ["nope", "", null, undefined, 3, "../neutral", "NEUTRAL"]) {
      expect(themeFor(bad)).toBe("studio");
    }
  });

  it("FR-WLD-15 committed theme files match the generator (run `just tokens`)", () => {
    const { css, ts } = generate(THEMES_DIR);
    expect(fs.readFileSync(CSS_PATH, "utf-8")).toBe(css);
    expect(fs.readFileSync(TS_PATH, "utf-8")).toBe(ts);
  });

  it("FR-WLD-15 a theme file added to config/themes is applied with no code change", () => {
    const dir = tempThemes({ "harbour.json": harbour });
    try {
      const { css, ts } = generate(dir);
      expect(ts).toContain('id: "harbour"');
      expect(css).toContain('[data-park][data-theme="harbour"]:not([data-time="night"]) {');
      expect(css).toContain("--ground: #c8c8c8;");
      expect(css).toContain('[data-park][data-theme="harbour"][data-time="night"] {');
      expect(css).toContain("--hero: #999999;");
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
    // The real folder is untouched: the added theme never appears in the committed output.
    expect(fs.readFileSync(CSS_PATH, "utf-8")).not.toContain("harbour");
  });

  it("FR-WLD-15 day and night values never cross: by day the night map is not applied, and the reverse", () => {
    const css = fs.readFileSync(CSS_PATH, "utf-8");
    const neutral = readThemes(THEMES_DIR).find((t) => t.id === "neutral");
    const day = css.split('[data-park][data-theme="neutral"]:not([data-time="night"]) {')[1] ?? "";
    const night = css.split('[data-park][data-theme="neutral"][data-time="night"] {')[1] ?? "";
    for (const [role, value] of Object.entries(neutral?.day ?? {})) {
      expect(day.split("}")[0]).toContain(`--${role}: ${value};`);
    }
    for (const [role, value] of Object.entries(neutral?.night ?? {})) {
      expect(night.split("}")[0]).toContain(`--${role}: ${value};`);
    }
    expect(css).not.toContain('[data-theme="metropolis"]'); // the default overrides nothing
    expect(css).not.toMatch(/transition|animation|url\(/);
  });

  it("FR-WLD-15 the second theme is neutral: grey role tokens only, no brand colour", () => {
    const neutral = readThemes(THEMES_DIR).find((t) => t.id === "neutral");
    const values = [
      ...Object.values(neutral?.day ?? {}),
      ...Object.values(neutral?.night ?? {}),
    ] as string[];
    expect(values.length).toBeGreaterThan(10);
    for (const v of values) {
      const [r = 0, g = 0, b = 0] = rgb(v);
      expect(Math.max(r, g, b) - Math.min(r, g, b), v).toBeLessThanOrEqual(8);
    }
    expect(values.join(" ")).not.toMatch(/5a3fe0|7a62f5|6c52eb/i); // Metropolis iris
    expect(Object.keys(neutral?.day ?? {})).not.toEqual(
      expect.arrayContaining(["ok", "red", "amber"]),
    );
  });

  it("FR-WLD-15 refuses a malformed theme file instead of writing it into the stylesheet", () => {
    const bad: Record<string, unknown> = {
      "id has caps": { ...harbour, id: "Harbour" },
      "role is a custom property": { ...harbour, day: { "--ground": "#fff" } },
      "value breaks out of the rule": { ...harbour, day: { ground: "#fff;}body{display:none" } },
      "value is a url": { ...harbour, day: { ground: "url(https://evil.example/x)" } },
      "unknown key": { ...harbour, css: "body{}" },
      "name too long": { ...harbour, name: "x".repeat(60) },
      "not an object": [1, 2],
    };
    for (const [why, body] of Object.entries(bad)) {
      expect(parseTheme(body), why).toBeNull();
    }
    expect(parseTheme(harbour)).toMatchObject({ id: "harbour", isDefault: false });
    const dir = tempThemes({ "harbour.json": { ...harbour, id: "other" } });
    try {
      expect(() => readThemes(dir)).toThrow(/harbour\.json/); // the id must equal the file name
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
    const twice = tempThemes({ "second.json": { ...harbour, id: "second", default: true } });
    try {
      expect(() => readThemes(twice)).toThrow(/default/);
    } finally {
      fs.rmSync(twice, { recursive: true, force: true });
    }
  });
});
