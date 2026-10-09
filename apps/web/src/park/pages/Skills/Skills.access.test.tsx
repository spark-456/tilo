// @vitest-environment happy-dom
// FR-ACC-02 on the Skills page: each skill's tools get a level picker that offers nothing above the team level.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, qa } from "../../../../test-support/park/componentsHarness";
import { mountSkills } from "../../../../test-support/park/skillsHarness";
import { skills } from "../../api/fixtures";
import { LEVEL_LABEL } from "../Connectors/view";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const pickers = (el: HTMLElement) => qa(el, "select[data-skill-tool]") as HTMLSelectElement[];

describe("FR-ACC-02 Skills page tool access", () => {
  it("FR-ACC-02 options above the team level are disabled and the shown value never exceeds it", async () => {
    const { el } = await mountSkills();
    const list = pickers(el);
    expect(list.length).toBeGreaterThan(0);
    for (const sel of list) {
      const team = Number(sel.dataset.teamLevel);
      const opts = [...sel.options];
      expect(opts.map((o) => o.text)).toEqual([...LEVEL_LABEL]);
      opts.forEach((o, i) => expect(o.disabled).toBe(i > team));
      expect(Number(sel.value)).toBeLessThanOrEqual(team);
    }
  });

  it("FR-ACC-02 a skill level above the team level in the data is shown as the team level", async () => {
    const tampered = skills.map((s) => ({
      ...s,
      tools: s.tools.map(([n]) => [n, 3] as [string, number]),
    }));
    const { skillsApi, fixtureResult } = await import(
      "../../../../test-support/park/skillsHarness"
    );
    const api = skillsApi({ getSkills: () => fixtureResult(tampered) });
    const { el } = await mountSkills({ api });
    for (const sel of pickers(el)) expect(Number(sel.value)).toBe(Number(sel.dataset.teamLevel));
  });

  it("FR-ACC-02 choosing a lower level changes the shown value", async () => {
    const { el } = await mountSkills();
    const sel = pickers(el).find((s) => Number(s.dataset.teamLevel) >= 2);
    if (!sel) throw new Error("no picker with a team level of Draft or Act");
    sel.value = "1";
    await act(async () => {
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(sel.value).toBe("1");
  });
});
