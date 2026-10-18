import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { declsFor, parseRules } from "../../test-support/park/componentsCss";

const teamCss = fs.readFileSync(path.join(__dirname, "pages/Team/Team.css"), "utf8");
const teamStudioCss = fs.readFileSync(path.join(__dirname, "pages/Team/Team.studio.css"), "utf8");
const ledgerCss = fs.readFileSync(path.join(__dirname, "pages/Ledger/Ledger.css"), "utf8");
const worldCss = fs.readFileSync(path.join(__dirname, "pages/World/World.css"), "utf8");
const worldStudioCss = fs.readFileSync(
  path.join(__dirname, "pages/World/World.studio.css"),
  "utf8",
);
const agendaCss = fs.readFileSync(path.join(__dirname, "pages/Agenda/Agenda.css"), "utf8");
const worldsCss = fs.readFileSync(path.join(__dirname, "pages/Worlds/Worlds.css"), "utf8");

describe("FT_UX_1 phone tap targets and team table scroll", () => {
  it("FT_UX_1 Team table scrolls inside its card container and has containment", () => {
    // Check .park-team-scroll has overflow-x: auto and max-width 100%
    const parsed = parseRules(teamCss).rules;
    const scrollRules = parsed.filter((r) => r.selector === "[data-park] .park-team-scroll");
    expect(scrollRules.length).toBeGreaterThan(0);
    const lastScroll = scrollRules[scrollRules.length - 1];
    expect(lastScroll?.decls.get("overflow-x")).toBe("auto");
    expect(lastScroll?.decls.get("max-width")).toBe("100%");

    // Studio sheet on phone has containment
    expect(teamStudioCss).toContain("overflow-x: hidden");
    expect(teamStudioCss).toContain(".park-team-dirtable");
  });

  it("FT_UX_1 Team phone tap targets are at least 44px", () => {
    const parsed = parseRules(teamCss).rules;
    const targets = [
      "park-team-link",
      "park-switch",
      "park-team-more",
      "park-team-btn",
      "park-team-select",
    ];
    for (const target of targets) {
      const d = declsFor(parsed, [target]);
      const px = (name: string) => Number.parseFloat(d.get(name) ?? "0") || 0;
      const h = Math.max(px("height"), px("min-height"));
      expect(h, `${target} height`).toBeGreaterThanOrEqual(44);
    }
  });

  it("FT_UX_1 Ledger phone tap targets are at least 44px", () => {
    const parsed = parseRules(ledgerCss).rules;
    const dMethod = declsFor(parsed, ["park-ledger-method"]);
    const px = (name: string) => Number.parseFloat(dMethod.get(name) ?? "0") || 0;
    const h = Math.max(px("height"), px("min-height"));
    expect(h, "park-ledger-method height").toBeGreaterThanOrEqual(44);
  });

  it("FT_UX_1 World phone tap targets are at least 44px", () => {
    const parsed = parseRules(worldCss).rules;
    const targets = [
      "park-world-skillchip",
      "park-world-toolchip",
      "park-world-chipfit",
      "park-world-back",
      "park-world-spendlink",
    ];
    for (const target of targets) {
      const d = declsFor(parsed, [target]);
      const px = (name: string) => Number.parseFloat(d.get(name) ?? "0") || 0;
      const h = Math.max(px("height"), px("min-height"));
      expect(h, `${target} height`).toBeGreaterThanOrEqual(44);
    }
    // Studio theme also defines 44px phone targets
    expect(worldStudioCss).toContain(".park-world-storyviewbtn");
    expect(worldStudioCss).toContain(".park-world-skillchip");
    expect(worldStudioCss).toContain(".park-world-toolchip");
  });

  it("FT_UX_1 Agenda phone tap targets are at least 44px", () => {
    const parsed = parseRules(agendaCss).rules;
    const targets = [
      "park-agenda-navbtn",
      "park-agenda-viewbtn",
      "park-agenda-filter",
      "park-agenda-slot",
      "park-agenda-event",
      "park-agenda-check",
      "park-agenda-accept",
      "park-agenda-notnow",
      "park-agenda-act",
      "park-agenda-addbtn",
      "park-agenda-pinit",
    ];
    for (const target of targets) {
      const d = declsFor(parsed, [target]);
      const px = (name: string) => Number.parseFloat(d.get(name) ?? "0") || 0;
      const h = Math.max(px("height"), px("min-height"));
      expect(h, `${target} height`).toBeGreaterThanOrEqual(44);
    }
  });

  it("FT_UX_1 Worlds phone routines meet 44px", () => {
    expect(worldsCss).toContain(".park-worlds-routines button");
    expect(worldsCss).toContain(".park-worlds-routines a");
  });
});
