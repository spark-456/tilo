// P0-08b W4: reserve the sample target in the flex row. Negative margins previously
// let Your context cover half of its nominal 24px box (12x24 clickable pixels).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";
import { parseRules } from "../../../test-support/park/componentsCss";
import { parseBlocks } from "../../../test-support/park/css";

const css = readFileSync(join(__dirname, "park.shell.css"), "utf8");
function atWidth(text: string, width: number): string {
  return parseBlocks(text)
    .map((block) => {
      if (!block.atRule) return `${block.selector} {${block.body}}`;
      const max = block.selector.match(/^@media\(max-width:(\d+)px\)$/);
      return max && width <= Number(max[1]) ? atWidth(block.body, width) : "";
    })
    .join("\n");
}
function declarations(selector: string, width: number): Map<string, string> {
  const out = new Map<string, string>();
  for (const rule of parseRules(atWidth(css, width)).rules) {
    if (rule.selector.replaceAll(" ", "") === selector.replaceAll(" ", "")) {
      for (const [key, value] of rule.decls) out.set(key, value);
    }
  }
  return out;
}
function edges(value: string): number[] {
  const [top = 0, right = top, bottom = top, left = right] = value
    .split(" ")
    .map(Number.parseFloat);
  return [top, right, bottom, left];
}

for (const width of [320, 360, 375, 390, 414]) {
  it(`P0_08b_W4_${width}_sample_reserves_its_full_24px_target_beside_context`, () => {
    const sample = declarations("[data-park] .park-shell__sample", width);
    const dot = declarations("[data-park] .park-shell__sampledot", width);
    const margins = edges(sample.get("margin") ?? "0");
    // A target must occupy its own space, not borrow a neighbour's hit area.
    expect(
      margins.every((edge) => edge >= 0),
      "sample margins reserve the entire target",
    ).toBe(true);
    const [top, right, bottom, left] = edges(sample.get("padding") ?? "0");
    const targetWidth = Math.max(
      Number.parseFloat(sample.get("min-width") ?? "0"),
      Number.parseFloat(dot.get("width") ?? "0") + (left ?? 0) + (right ?? 0),
    );
    const targetHeight = Math.max(
      Number.parseFloat(sample.get("min-height") ?? "0"),
      Number.parseFloat(dot.get("height") ?? "0") + (top ?? 0) + (bottom ?? 0),
    );
    expect(targetWidth).toBeGreaterThanOrEqual(24);
    expect(targetHeight).toBeGreaterThanOrEqual(24);
  });
}
