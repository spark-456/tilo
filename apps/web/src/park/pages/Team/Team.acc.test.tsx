// @vitest-environment happy-dom
// FR-TEAM-02 / FR-TEAM-04 on the Team page (fixture data, labelled sample): nobody changes their own role;
// the Must-ask switches are locked on and every switch change is logged on the page.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, makeApp, renderTeam } from "../../../../test-support/park/teamHarness";
import { canChangeRole } from "./teamModel";
import { clickAndSettle, region, switchNamed } from "./testApp";

afterEach(cleanup);

describe("FR-TEAM-02 roles", () => {
  it("FR-TEAM-02 canChangeRole refuses your own row and anyone below Approver", () => {
    expect(canChangeRole({ id: "a", role: "Owner" }, { id: "a", role: "Owner" })).toBe(false);
    expect(canChangeRole({ id: "a", role: "Owner" }, { id: "b", role: "Member" })).toBe(true);
    expect(canChangeRole({ id: "a", role: "Member" }, { id: "b", role: "Viewer" })).toBe(false);
    expect(canChangeRole({ id: "a", role: "Approver" }, { id: "b", role: "Owner" })).toBe(false);
  });

  it("FR-TEAM-02 your own role select is the only disabled one on the page", async () => {
    const { root } = await renderTeam(makeApp());
    const locked = [...root.querySelectorAll("select")].filter(
      (s) => (s as HTMLSelectElement).disabled,
    );
    expect(locked.map((s) => s.getAttribute("aria-label"))).toEqual(["Role for Alex Morgan"]);
  });
});

describe("FR-TEAM-04 stop-and-ask switches", () => {
  it("FR-TEAM-04 Must-ask switches are locked on; the optional one changes and is logged", async () => {
    const { root } = await renderTeam(makeApp());
    const rules = region(root, "Approval rules");
    for (const name of [
      "Spending over £250",
      "Sharing anything outside the company",
      "Actions that can’t be undone",
    ]) {
      const sw = switchNamed(rules, name) as HTMLButtonElement;
      expect(sw.disabled, name).toBe(true);
      expect(sw.getAttribute("aria-checked")).toBe("true");
    }
    expect(root.querySelector('[aria-label="Rule changes"]')).toBeNull();
    await clickAndSettle(switchNamed(rules, "Routines that fall on a weekend"));
    const log = region(root, "Rule changes");
    expect(log.textContent).toMatch(/Routines that fall on a weekend/);
    expect(log.textContent).toMatch(/On/);
  });
});
