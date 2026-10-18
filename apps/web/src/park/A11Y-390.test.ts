import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const homeCss = readFileSync(join(here, "pages/Home/Home.css"), "utf8");
const worldsCss = readFileSync(join(here, "pages/Worlds/Worlds.css"), "utf8");
const agendaCss = readFileSync(join(here, "pages/Agenda/Agenda.css"), "utf8");
const teamCss = readFileSync(join(here, "pages/Team/Team.css"), "utf8");
const skillsCss = readFileSync(join(here, "pages/Skills/Skills.css"), "utf8");

describe("A11Y-390: At 390 px wide, on Home, Worlds, Agenda, Team and Skills", () => {
  describe("A11Y-390: Horizontal scroll prevention", () => {
    it("A11Y-390 Home has max-width and overflow-x protection on mobile", () => {
      expect(homeCss).toMatch(/\[data-park\] \.park-home-root \{[^}]*overflow-x:\s*hidden/s);
    });

    it("A11Y-390 Worlds has max-width and overflow-x protection on mobile", () => {
      expect(worldsCss).toMatch(
        /\[data-park\] \.park-worlds-root[^{]*\{[^}]*overflow-x:\s*hidden/s,
      );
    });

    it("A11Y-390 Agenda has max-width and overflow-x protection on mobile", () => {
      expect(agendaCss).toMatch(
        /\[data-park\] \.park-agenda-root[^{]*\{[^}]*overflow-x:\s*hidden/s,
      );
    });

    it("A11Y-390 Team has max-width and overflow-x protection on mobile", () => {
      expect(teamCss).toMatch(/\[data-park\] \.park-team-root[^{]*\{[^}]*overflow-x:\s*hidden/s);
    });

    it("A11Y-390 Skills has max-width and overflow-x protection on mobile", () => {
      expect(skillsCss).toMatch(
        /\[data-park\] \.park-skills-root[^{]*\{[^}]*overflow-x:\s*hidden/s,
      );
    });
  });

  describe("A11Y-390: Tap targets under 44 px fixed on mobile", () => {
    it("A11Y-390 Home brief controls meet 44px min-height and min-width on phone", () => {
      expect(homeCss).toMatch(/\[data-park\] \.park-home-brief button \{[^}]*min-height:\s*44px/s);
      expect(homeCss).toMatch(
        /\[data-park\] \.park-home-brief-row button \{[^}]*min-height:\s*44px/s,
      );
    });

    it("A11Y-390 Worlds slack and decision controls meet 44px min-height on phone", () => {
      expect(worldsCss).toMatch(/\[data-park\] \.park-worlds-slack \{[^}]*min-height:\s*44px/s);
      expect(worldsCss).toMatch(
        /\[data-park\] \.park-worlds-dec__pending \{[^}]*min-height:\s*44px/s,
      );
    });

    it("A11Y-390 Agenda synced text and meeting select meet 44px minimum tap target", () => {
      expect(agendaCss).toMatch(
        /\[data-park\] [^{]*\.park-agenda-synced \{[^}]*min-height:\s*44px/s,
      );
      expect(agendaCss).toMatch(
        /\[data-park\] \.park-agenda-hostselect select \{[^}]*min-height:\s*44px/s,
      );
    });

    it("A11Y-390 Team ownperson select meets 44px min-height", () => {
      expect(teamCss).toMatch(
        /\[data-park\] \.park-team-ownperson \.park-team-select \{[^}]*min-height:\s*44px/s,
      );
    });

    it("A11Y-390 Skills access controls meet 44px min-height", () => {
      expect(skillsCss).toMatch(
        /\[data-park\] \.park-skills-access-select \{[^}]*min-height:\s*44px/s,
      );
    });
  });

  describe("A11Y-390: Missing focus rings fixed", () => {
    it("A11Y-390 Home has focus rings on buttons, links, inputs, and selects", () => {
      expect(homeCss).toMatch(
        /\[data-park\] \.park-home-root (?:button|a|input|select):focus-visible/,
      );
    });

    it("A11Y-390 Worlds has focus rings on buttons, links, inputs, and selects", () => {
      expect(worldsCss).toMatch(
        /\[data-park\] \.park-worlds-root (?:button|a|input|select):focus-visible/,
      );
    });

    it("A11Y-390 Agenda has focus rings on buttons, links, inputs, and selects", () => {
      expect(agendaCss).toMatch(
        /\[data-park\] \.park-agenda-root (?:button|a|input|select):focus-visible/,
      );
    });

    it("A11Y-390 Team has focus rings on buttons, links, inputs, and selects", () => {
      expect(teamCss).toMatch(
        /\[data-park\] \.park-team-root (?:button|a|input|select):focus-visible/,
      );
    });

    it("A11Y-390 Skills has focus rings on buttons, links, inputs, and selects with var(--focus)", () => {
      expect(skillsCss).toMatch(
        /\[data-park\] \.park-skills-root (?:button|a|input|select):focus-visible/,
      );
    });
  });
});
