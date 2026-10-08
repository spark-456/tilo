// TEAM-WEB: no page imports another page (shared code lives outside both, e.g. park/app).
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const PAGES = path.resolve(__dirname, "..");

describe("TEAM_WEB_static: pages do not import pages", () => {
  it("TEAM_WEB_static_Team_and_Connectors_import_no_other_page", () => {
    const bad: string[] = [];
    for (const page of ["Team", "Connectors"]) {
      const dir = path.join(PAGES, page);
      for (const f of readdirSync(dir).filter((n) => /\.tsx?$/.test(n) && !/\.test\./.test(n))) {
        const src = readFileSync(path.join(dir, f), "utf8");
        for (const m of src.matchAll(/(?:\bfrom|\bimport)\s*\(?\s*["']([^"']+)["']/g)) {
          const spec = m[1] ?? "";
          if (!spec.startsWith(".")) continue;
          const target = path.resolve(dir, spec);
          const rel = path.relative(PAGES, target).replaceAll("\\", "/");
          if (!rel.startsWith("..") && rel.split("/")[0] !== page)
            bad.push(`${page}/${f} imports ${spec}`);
        }
      }
    }
    expect(bad).toEqual([]);
  });
});
