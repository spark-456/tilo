// WEB-9 Agenda static rules (helper contract, plan section 10): every selector under [data-park] with the
// park-agenda- prefix, no motion in page code, no escape hatches, nothing from screens/world/stage.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const DIR = __dirname;
const src = readdirSync(DIR)
  .filter((f) => /\.(tsx?|css)$/.test(f) && !/\.test\.tsx?$/.test(f) && f !== "agendaHarness.tsx")
  .map((f) => ({ f, t: readFileSync(join(DIR, f), "utf8") }));
const strip = (t: string) =>
  t.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");

describe("WEB_9_agenda_static", () => {
  it("WEB_9_agenda_files_exist", () => {
    const names = src.map((s) => s.f);
    for (const f of ["AgendaPage.tsx", "Agenda.css", "index.ts", "model.ts", "appCtx.ts"])
      expect(names, f).toContain(f);
  });

  it("WEB_9_agenda_css_selectors_sit_under_data_park_with_the_prefix", () => {
    const css = strip(src.find((s) => s.f === "Agenda.css")?.t ?? "");
    const selectors = [...css.matchAll(/([^{}]+)\{/g)].flatMap((m) =>
      (m[1] ?? "")
        .split(",")
        .map((x) => x.trim())
        .filter((x) => x && !x.startsWith("@")),
    );
    expect(selectors.length).toBeGreaterThan(10);
    for (const s of selectors) {
      expect(s.startsWith("[data-park] "), s).toBe(true);
      expect(s.includes("park-agenda-"), s).toBe(true);
    }
  });

  it("WEB_9_agenda_no_motion_no_timers_no_escape_hatches", () => {
    for (const { f, t } of src) {
      const c = strip(t);
      expect(c, f).not.toMatch(
        /\btransition\b|\banimation\b|@keyframes|\bsetTimeout\b|\bsetInterval\b|requestAnimationFrame/,
      );
      expect(c, f).not.toMatch(
        /dangerouslySetInnerHTML|@ts-ignore|:\s*any\b|\bas any\b|<any>|\bwindow\b|globalThis|\beval\s*\(/,
      );
      expect(c, f).not.toMatch(/from\s+["'][^"']*\/(screens|world|stage)\//);
      expect(c, f).not.toMatch(/\b(?:gemini|gpt|claude|llama)-/i);
      expect(/support\.js|tilo-app\.js/i.test(c), f).toBe(false);
      expect(c, f).not.toMatch(/Math\.random|Date\.now|new Date|fetch\(/);
    }
  });
});
