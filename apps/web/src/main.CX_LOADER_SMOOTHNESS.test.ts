import { readFileSync, readdirSync } from "node:fs";
import { expect, it } from "vitest";

const main = readFileSync(new URL("./main.tsx", import.meta.url), "utf8");
const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
// The cover stylesheet is content-hashed (served immutable), so a changed rule never meets a stale copy.
const coverName = html.match(/href="\/loader\/(boot-cover-[0-9a-f]{12}\.css)"/)?.[1] ?? "";
const coverCss = readFileSync(new URL(`../public/loader/${coverName}`, import.meta.url), "utf8");

it("CX_LOADER_SMOOTHNESS_defers_app_code_and_font_styles_until_after_first_paint", () => {
  expect(main).toMatch(/installBootCover\(\)/);
  expect(main).toMatch(/afterFirstPaint/);
  expect(main).toMatch(/import\(["']\.\/startApp["']\)/);
  expect(main).not.toMatch(/@fontsource|styles\/app\.css|from ["']\.\/Root["']/);
});

it("CX_LOADER_SMOOTHNESS_uses_a_fixed_intrinsic_size_cover_without_layout_flow", () => {
  expect(readdirSync(new URL("../public/loader/", import.meta.url))).toContain(coverName);
  expect(html).toMatch(/<link rel="stylesheet" href="\/loader\/boot-cover-[0-9a-f]{12}\.css"/);
  expect(html).not.toMatch(/<style/); // CSP style-src is 'self' only (P0-07e)
  expect(html.indexOf("boot-cover-")).toBeLessThan(html.indexOf('id="tilo-boot-cover"'));
  expect(coverCss).toMatch(/#tilo-boot-cover\s*\{[^}]*position:\s*fixed/);
  expect(html).toMatch(/<img[^>]+width="552"[^>]+height="727"/);
});

it("CX_LOADER_SMOOTHNESS_cover_artwork_is_centred_and_sized_to_fit_the_viewport", () => {
  // the artwork canvas is centred on the pool; the cover sizes by width and height, so it is never cut off
  expect(coverCss).toMatch(/place-items:\s*center/);
  expect(coverCss).toMatch(/img\{[^}]*width:min\(460px,92vw,calc\(88vh \* \.759\)\)/);
});
