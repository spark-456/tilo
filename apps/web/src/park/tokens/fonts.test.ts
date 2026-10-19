// WEB-1a (README "Typography"; plan section 2): src/park/tokens/fonts.ts imports Nunito 800/900 and
// Nunito Sans 400/600/700/800 from the @fontsource packages that are already installed (side-effect
// imports only), and docs/licences.md still covers both packages (CLAUDE.md: record every licence).
// No new dependency: the fonts are self-hosted by the packages in apps/web/package.json.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { PARK_DIR, REPO_ROOT } from "../../../test-support/park/prototype";

const FONTS_TS = path.join(PARK_DIR, "tokens", "fonts.ts");
const WEB_DIR = path.resolve(PARK_DIR, "..", "..");

const EXPECTED = [
  "@fontsource/nunito/800.css",
  "@fontsource/nunito/900.css",
  "@fontsource/nunito-sans/400.css",
  "@fontsource/nunito-sans/600.css",
  "@fontsource/nunito-sans/700.css",
  "@fontsource/nunito-sans/800.css",
];

const source = (): string => fs.readFileSync(FONTS_TS, "utf8");
const importLines = (src: string): string[] =>
  src
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => /^import\b/.test(l));

describe("WEB_1a_fonts: Nunito and Nunito Sans imports", () => {
  it("WEB_1a_fonts_ts_exists", () => {
    expect(fs.existsSync(FONTS_TS), `${FONTS_TS} must exist`).toBe(true);
  });

  it("WEB_1a_fonts_exactly_the_six_weights_as_side_effect_imports", () => {
    const imports = importLines(source());
    const specifiers = imports.map((l) => l.match(/^import\s+["']([^"']+)["'];?$/)?.[1]);
    expect(specifiers.sort(), "only side-effect imports of the six font files").toEqual(
      [...EXPECTED].sort(),
    );
    expect(
      imports.some((l) => /\bfrom\b/.test(l)),
      "no named or default imports",
    ).toBe(false);
  });

  it("WEB_1a_fonts_each_import_resolves_to_an_installed_file", () => {
    for (const spec of EXPECTED) {
      const file = path.join(WEB_DIR, "node_modules", ...spec.split("/"));
      expect(fs.existsSync(file), `${spec} is not installed (${file})`).toBe(true);
    }
  });

  it("WEB_1a_fonts_ts_is_side_effect_only_it_exports_nothing", () => {
    expect(source()).not.toMatch(/^\s*export\b/m);
  });
});

describe("WEB_1a_fonts: packages and licences", () => {
  it("WEB_1a_fonts_packages_are_already_dependencies", () => {
    const pkg = JSON.parse(fs.readFileSync(path.join(WEB_DIR, "package.json"), "utf8")) as {
      dependencies: Record<string, string>;
    };
    expect(Object.keys(pkg.dependencies)).toContain("@fontsource/nunito");
    expect(Object.keys(pkg.dependencies)).toContain("@fontsource/nunito-sans");
  });

  it("WEB_1a_fonts_licences_register_covers_both_packages", () => {
    const text = fs.readFileSync(path.join(REPO_ROOT, "docs", "licences.md"), "utf8");
    expect(text).toContain("@fontsource/nunito");
    expect(text).toContain("@fontsource/nunito-sans");
    expect(text).toMatch(/Nunito Sans/);
    expect(text).toMatch(/OFL-1\.1/);
  });
});
