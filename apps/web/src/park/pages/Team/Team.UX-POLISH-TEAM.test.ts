import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "Team.css"), "utf8");
const sources = ["Members.tsx", "Coverage.tsx", "SelfServeTeams.tsx"].map((file) =>
  readFileSync(join(here, file), "utf8"),
);

describe("UX_POLISH_TEAM", () => {
  it("UX_POLISH_TEAM_replaces_browser_select_arrows_across_team_controls", () => {
    for (const source of sources) expect(source).toContain('className="park-team-selectwrap"');
    expect(css).toMatch(/\.park-team-select \{[^}]*appearance: none/s);
    expect(css).toMatch(/\.park-team-selectwrap::after \{[^}]*content: "⌄"/s);
  });

  it("UX_POLISH_TEAM_replaces_the_browser_details_marker", () => {
    expect(css).toMatch(/\.park-team-summary \{[^}]*list-style: none/s);
    expect(css).toContain(".park-team-summary::-webkit-details-marker");
    expect(css).toMatch(/\.park-team-summary::after \{[^}]*content: "⌄"/s);
  });
});
