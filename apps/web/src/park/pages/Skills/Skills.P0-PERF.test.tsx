// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { mountSkills, skillsApi } from "../../../../test-support/park/skillsHarness";

afterEach(() => vi.restoreAllMocks());

it("P0_PERF_keeps_the_skills_list_when_only_the_viewport_changes", async () => {
  const fixture = skillsApi();
  const result = await fixture.getSkills();
  const map = vi.spyOn(result.data, "map");
  const api = skillsApi({ getSkills: () => Promise.resolve(result) });
  const rig = await mountSkills({ api });
  const initial = map.mock.calls.length;
  expect(initial).toBeGreaterThan(0);
  await rig.update({ vw: 390 });
  expect(map.mock.calls.length).toBe(initial);
  rig.m.unmount();
});
