// @vitest-environment happy-dom
// POLISH-1 (design review DESIGN-LIVE11, design/studio-v2): phone tap targets, the Team matrix as a focusable region,
// the Home placeholder and metric grid, Skills' folded tool-access list and one icon tile, one page container.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { parseRules } from "../../test-support/park/componentsCss";
import { cleanup, press, qa } from "../../test-support/park/componentsHarness";
import { mountSkills } from "../../test-support/park/skillsHarness";
import { makeApp, renderTeam } from "../../test-support/park/teamHarness";
import { ACCESS_PREVIEW } from "./pages/Skills/ToolAccess";

afterEach(cleanup);

const css = (file: string) => readFileSync(join(__dirname, file), "utf8");
/** The declarations of one selector, merged over every rule that names it (the last wins). */
function decls(sheet: string, selector: string): ReadonlyMap<string, string> {
  const all = parseRules(sheet).rules.filter((r) => r.selector === selector);
  return new Map(all.flatMap((r) => [...r.decls]));
}
/** The first rule that names the selector (the base rule, before any phone override). */
const baseDecls = (sheet: string, selector: string): ReadonlyMap<string, string> =>
  parseRules(sheet).rules.find((r) => r.selector === selector)?.decls ?? new Map();
/** The text of the media block that starts with `query`. */
function block(sheet: string, query: string): string {
  const at = sheet.indexOf(query);
  expect(at, query).toBeGreaterThanOrEqual(0);
  let depth = 0;
  for (let i = sheet.indexOf("{", at); i < sheet.length; i++) {
    if (sheet[i] === "{") depth++;
    if (sheet[i] === "}" && --depth === 0) return sheet.slice(sheet.indexOf("{", at) + 1, i);
  }
  throw new Error(`unclosed ${query}`);
}

describe("UI_POLISH_1 phone tap targets", () => {
  const shell = css("shell/park.shell.css");
  const phone = block(shell, "@media (min-width: 361px) and (max-width: 560px)");
  it.each([
    ".park-shell__logo",
    ".park-shell__iconbtn",
    ".park-shell__sample",
    ".park-shell__avatar",
  ])("UI_POLISH_1 %s is at least 44x44 on a 390px phone", (cls) => {
    const d = decls(phone, `[data-park] ${cls}`);
    expect(Number.parseFloat(d.get("min-width") ?? "0")).toBeGreaterThanOrEqual(44);
    expect(Number.parseFloat(d.get("min-height") ?? "0")).toBeGreaterThanOrEqual(44);
  });
});

describe("UI_POLISH_1 Team", () => {
  it("UI_POLISH_1 the role matrix is a named, keyboard-focusable region (scrollable-region-focusable)", async () => {
    const { root } = await renderTeam(makeApp());
    const matrix = root.querySelector<HTMLElement>(".park-team-matrix");
    expect(matrix).not.toBeNull();
    expect(matrix?.tabIndex).toBe(0);
    expect(matrix?.getAttribute("aria-label")).toBe("What each role can do");
    expect(css("pages/Team/Team.css")).toContain(".park-team-matrix:focus-visible");
  });
});

describe("UI_POLISH_1 Home", () => {
  const home = css("pages/Home/Home.css");
  it("UI_POLISH_1 an odd last metric tile takes the whole row, and 3-column widths use a six-column grid", () => {
    expect(
      decls(home, "[data-park] .park-home-kpis > :last-child:nth-child(odd)").get("grid-column"),
    ).toBe("1 / -1");
    const mid = block(home, "@media (min-width: 841px) and (max-width: 1179px)");
    expect(decls(mid, "[data-park] .park-home-kpis").get("grid-template-columns")).toContain(
      "repeat(6",
    );
    expect(
      decls(mid, "[data-park] .park-home-kpis > :nth-child(5):last-child").get("grid-column"),
    ).toBe("span 3");
  });
  it("UI_POLISH_1 the phone task box type is 16px so the example is not cut", () => {
    const small = block(home, "@media (max-width: 430px)");
    expect(decls(small, "[data-park] .park-home-panel .park-home-input").get("font-size")).toBe(
      "16px",
    );
  });
});

describe("UI_POLISH_1 Skills", () => {
  it("UI_POLISH_1 tool access shows the first rows and the rest after Show all", async () => {
    const { el } = await mountSkills();
    const rows = () => qa(el, "select[data-skill-tool]").length;
    expect(rows()).toBe(ACCESS_PREVIEW);
    const more = qa(el, "button.park-skills-access-more")[0] as HTMLButtonElement;
    expect(more.textContent).toMatch(/^Show all \d+$/);
    expect(more.getAttribute("aria-expanded")).toBe("false");
    press(more, "Enter");
    expect(rows()).toBeGreaterThan(ACCESS_PREVIEW);
    expect(more.getAttribute("aria-expanded")).toBe("true");
    expect(more.textContent).toBe("Show fewer");
  });

  it("UI_POLISH_1 every skill icon tile is one size and style", () => {
    const studio = css("pages/Skills/SkillsStudio.css");
    const tail = studio.slice(studio.lastIndexOf("POLISH-1: one icon tile"));
    for (const cls of [
      ".park-skills-card2__art",
      ".park-skills-ask-avatar",
      ".park-skills-review-avatar",
      ".park-skills-lib-row-tile",
    ]) {
      expect(tail).toContain(`[data-park] ${cls}`);
    }
    expect(tail).toMatch(
      /width: 48px;\s+height: 48px;\s+border-radius: 15px;\s+background: var\(--sunk\);/,
    );
  });
});

describe("UI_POLISH_1 one page container", () => {
  it("UI_POLISH_1 Home, Worlds and Team take the shell's page width and gutter", () => {
    expect(css("shell/park.shell.css")).toContain("--park-page-max: 1296px");
    const home = baseDecls(css("pages/Home/Home.css"), "[data-park] .park-home-root");
    expect(home.get("max-width")).toBe("1296px"); // the token's value; Home's own pin test keeps the literal
    expect(home.get("padding")).toBe("120px 8px 64px"); // 8px = --park-page-pad
    expect(css("shell/park.shell.css")).toContain("--park-page-pad: 8px");
    for (const [file, id] of [
      ["shell/park.shell.css", "park-page-worlds"],
      ["pages/Team/Team.studio.css", "park-page-team"],
    ] as const) {
      const sel = `[data-park][data-theme="studio"] [data-testid="${id}"] > .park-sheet`;
      const d = baseDecls(css(file), sel);
      expect(d.get("max-width"), file).toContain("--park-page-max");
      expect(d.get("padding"), file).toContain("--park-page-pad");
    }
  });
});
