import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseRules } from "../../../test-support/park/componentsCss";

describe("FT-SITE-BLUR site loader blur and filter prohibition", () => {
  const dir = __dirname;
  const poolLoaderCss = fs.readFileSync(path.join(dir, "PoolLoader.css"), "utf8");
  const motionCss = fs.readFileSync(path.join(dir, "motion.css"), "utf8");

  it("PoolLoader.css has no filter or backdrop-filter with blur on the site cover", () => {
    const { rules } = parseRules(poolLoaderCss);
    const siteCoverRules = rules.filter((r) =>
      r.selector.includes(".tt-pool-page") ||
      r.selector.includes(".tt-pool-overlay") ||
      r.selector.includes(".tt-pool-scrim"),
    );

    for (const rule of siteCoverRules) {
      const filter = rule.decls.get("filter") ?? "";
      const backdropFilter = rule.decls.get("backdrop-filter") ?? rule.decls.get("-webkit-backdrop-filter") ?? "";
      expect(filter, `${rule.selector} must not carry blur in filter`).not.toMatch(/blur/i);
      expect(backdropFilter, `${rule.selector} must not carry blur in backdrop-filter`).not.toMatch(/blur/i);
    }
  });

  it("PoolLoader.css has zero backdrop-filter and zero filter declarations across all pool classes", () => {
    const { rules } = parseRules(poolLoaderCss);
    const poolRules = rules.filter((r) => r.selector.includes(".tt-pool"));
    for (const rule of poolRules) {
      expect(rule.decls.has("backdrop-filter"), `${rule.selector} has backdrop-filter`).toBe(false);
      expect(rule.decls.has("-webkit-backdrop-filter"), `${rule.selector} has -webkit-backdrop-filter`).toBe(false);
      const filter = rule.decls.get("filter");
      if (filter) {
        expect(filter, `${rule.selector} filter must not blur`).not.toMatch(/blur/i);
      }
    }
  });

  it("motion.css pool loader rules have no blur filter or backdrop-filter", () => {
    const { rules } = parseRules(motionCss);
    const poolMotionRules = rules.filter((r) => r.selector.includes(".tt-pool"));
    for (const rule of poolMotionRules) {
      const filter = rule.decls.get("filter") ?? "";
      const backdrop = rule.decls.get("backdrop-filter") ?? rule.decls.get("-webkit-backdrop-filter") ?? "";
      expect(filter, `${rule.selector} in motion.css must not blur`).not.toMatch(/blur/i);
      expect(backdrop, `${rule.selector} in motion.css must not have backdrop-filter`).toBe("");
    }
  });

  it("boot-cover stylesheets have no filter or backdrop-filter", () => {
    const loaderDir = path.resolve(dir, "../../../public/loader");
    if (fs.existsSync(loaderDir)) {
      const files = fs.readdirSync(loaderDir).filter((f) => f.startsWith("boot-cover-") && f.endsWith(".css"));
      for (const file of files) {
        const content = fs.readFileSync(path.join(loaderDir, file), "utf8");
        expect(content).not.toMatch(/backdrop-filter/i);
        expect(content).not.toMatch(/filter\s*:[^;]*blur/i);
      }
    }
  });

  it("AppShell does not trigger full-page pool loader after sign-in / demo start", () => {
    const appShellTsx = fs.readFileSync(
      path.resolve(dir, "../../park/shell/AppShell.tsx"),
      "utf8",
    );
    // Pool on first boot only (held by #tilo-boot-cover in HTML); in-place skeletons after
    expect(appShellTsx).not.toMatch(/<PoolLoader[^>]*loading=\{!ready && !document\.getElementById/);
  });
});
