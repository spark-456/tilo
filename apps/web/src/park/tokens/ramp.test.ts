// WEB-1a (BQ-WEB-4, plan section 9 decision C): Park pages are scoped under [data-park] with their own
// type ramp, pinned here against the README typography table. The design's ramp wins on Park pages and
// differs from PRD 18.2; the existing type-ramp.spec.ts stays unchanged for the old screens.
// Shape of tokens/ramp.ts (this test defines it): `TYPE_RAMP`, one entry per README row, keyed
//   pageTitle, sectionTitle, cardTitle, detailTitle, kpiValue, body, rowTitle, meta, eyebrow, logo,
// each { family: "Nunito" | "Nunito Sans"; weight: number | [min, max]; size: number | [min, max];
//        letterSpacing?: number (px); lineHeight?: number; uppercase?: true }.
import fs from "node:fs";
import { describe, expect, it } from "vitest";
import { HANDOFF_README_PATH } from "../../../test-support/park/prototype";
import { TYPE_RAMP } from "./ramp";

type Num = number | [number, number];
interface Parsed {
  family: string;
  weight: Num;
  size: Num;
  letterSpacing?: number;
  lineHeight?: number;
  uppercase?: true;
}

const ROLE_KEYS: Record<string, string> = {
  "Page title (h1)": "pageTitle",
  "Section title": "sectionTitle",
  "Card title": "cardTitle",
  "Detail title": "detailTitle",
  "KPI value": "kpiValue",
  Body: "body",
  "Row title": "rowTitle",
  "Meta / caption": "meta",
  Eyebrow: "eyebrow",
  Logo: "logo",
};

const range = (a: string, b: string | undefined): Num => (b ? [Number(a), Number(b)] : Number(a));

function parseReadmeRamp(): Record<string, Parsed> {
  const lines = fs.readFileSync(HANDOFF_README_PATH, "utf8").split(/\r?\n/);
  const start = lines.findIndex((l) => l.trim() === "### Typography");
  expect(start, "README has a ### Typography section").toBeGreaterThan(-1);
  const out: Record<string, Parsed> = {};
  for (const line of lines.slice(start + 1)) {
    if (line.startsWith("### ") || line.startsWith("## ")) break;
    if (!line.startsWith("|")) continue;
    const cells = line.split("|").map((c) => c.trim());
    const role = cells[1] ?? "";
    const spec = cells[2] ?? "";
    const key = ROLE_KEYS[role];
    if (!key) continue; // header and separator rows
    const parsed: Partial<Parsed> = {};
    for (const part of spec.split("·").map((p) => p.trim())) {
      const font = part.match(/^(Nunito Sans|Nunito) (\d+)(?:[–-](\d+))?$/);
      const spacing = part.match(/^([−+-])(\d+(?:\.\d+)?)px$/);
      const size = part.match(/^(\d+(?:\.\d+)?)(?:[–-](\d+(?:\.\d+)?))?px$/);
      const lh = part.match(/^lh (\d+(?:\.\d+)?)$/);
      if (font) {
        parsed.family = font[1] ?? "";
        parsed.weight = range(font[2] ?? "", font[3]);
      } else if (spacing) {
        parsed.letterSpacing = (spacing[1] === "+" ? 1 : -1) * Number(spacing[2]);
      } else if (size) {
        parsed.size = range(size[1] ?? "", size[2]);
      } else if (lh) {
        parsed.lineHeight = Number(lh[1]);
      } else if (part === "UPPERCASE") {
        parsed.uppercase = true;
      }
    }
    out[key] = parsed as Parsed;
  }
  return out;
}

describe("WEB_1a_ramp: the type ramp is the README table", () => {
  const readme = parseReadmeRamp();

  it("WEB_1a_ramp_readme_table_parses", () => {
    expect(Object.keys(readme).sort()).toEqual(Object.values(ROLE_KEYS).sort());
    for (const [key, row] of Object.entries(readme)) {
      expect(row.family, key).toMatch(/^Nunito/);
      expect(row.size, `${key} size`).toBeDefined();
    }
  });

  it("WEB_1a_ramp_sizes_are_the_design_sizes", () => {
    // Literal anchors from the ticket, so a wrong README parse cannot pass quietly.
    expect(TYPE_RAMP.pageTitle.size).toBe(36);
    expect(TYPE_RAMP.sectionTitle.size).toBe(24);
    expect(TYPE_RAMP.cardTitle.size).toEqual([17, 18]);
    expect(TYPE_RAMP.detailTitle.size).toBe(22);
    expect(TYPE_RAMP.kpiValue.size).toBe(28);
    expect(TYPE_RAMP.body.size).toEqual([14.5, 15.5]);
    expect(TYPE_RAMP.rowTitle.size).toBe(14.5);
    expect(TYPE_RAMP.meta.size).toEqual([12.5, 13]);
    expect(TYPE_RAMP.eyebrow.size).toBe(12);
    expect(TYPE_RAMP.logo.size).toBe(27);
  });

  it("WEB_1a_ramp_every_row_matches_the_readme_family_weight_spacing_and_line_height", () => {
    expect(Object.keys(TYPE_RAMP).sort()).toEqual(Object.keys(readme).sort());
    for (const [key, expected] of Object.entries(readme)) {
      const got = (TYPE_RAMP as unknown as Record<string, Parsed>)[key];
      expect(got, key).toEqual(expected);
    }
  });

  it("WEB_1a_ramp_fonts_are_the_two_handoff_families", () => {
    for (const row of Object.values(TYPE_RAMP)) {
      expect(["Nunito", "Nunito Sans"]).toContain(row.family);
    }
    expect(TYPE_RAMP.pageTitle.family).toBe("Nunito");
    expect(TYPE_RAMP.logo.family).toBe("Nunito");
    expect(TYPE_RAMP.rowTitle.family).toBe("Nunito Sans");
  });

  it("WEB_1a_ramp_is_plain_data", () => {
    // Serialisable: numbers, strings, one boolean flag. No functions, no CSS strings with em units.
    expect(JSON.parse(JSON.stringify(TYPE_RAMP))).toEqual(TYPE_RAMP);
    expect(JSON.stringify(TYPE_RAMP)).not.toMatch(/\bem\b|rem/);
  });
});
