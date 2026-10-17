import { readFileSync } from "node:fs";
import { expect, it } from "vitest";

const main = readFileSync(new URL("./main.tsx", import.meta.url), "utf8");
const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

it("CX_LOADER_SMOOTHNESS_defers_app_code_and_font_styles_until_after_first_paint", () => {
  expect(main).toMatch(/installBootCover\(\)/);
  expect(main).toMatch(/afterFirstPaint/);
  expect(main).toMatch(/import\(["']\.\/startApp["']\)/);
  expect(main).not.toMatch(/@fontsource|styles\/app\.css|from ["']\.\/Root["']/);
});

it("CX_LOADER_SMOOTHNESS_uses_a_fixed_intrinsic_size_cover_without_layout_flow", () => {
  expect(html).toMatch(/#tilo-boot-cover\s*\{[^}]*position:\s*fixed/);
  expect(html).toMatch(/<img[^>]+width="560"[^>]+height="412"/);
});
