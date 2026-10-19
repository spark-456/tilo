import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const page = readFileSync(new URL("./WorldPage.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("./World.studio.css", import.meta.url), "utf8");

describe("R-HEADER long world titles", () => {
  it("R-HEADER keeps the full title available and clamps the visible title to two lines", () => {
    expect(page).toMatch(/<h1 className="park-world-h1"[^>]*title=\{w\.name\}/);
    expect(css).toMatch(
      /\.park-world-h1\s*\{[^}]*display:\s*-webkit-box;[^}]*-webkit-line-clamp:\s*2;[^}]*overflow:\s*hidden;/s,
    );
    expect(css).toMatch(
      /@media \(min-width: 1280px\)[\s\S]*?\.park-world-titles\s*\{[^}]*flex:\s*1 1 280px;/,
    );
  });
});
