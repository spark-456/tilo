// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { mountSkills, skillsApi } from "../../../../test-support/park/skillsHarness";
import { SkillGrid } from "./Gallery";

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

it("P0_PERF_keeps_the_filtered_skill_cards_when_only_pause_state_changes", async () => {
  const result = await skillsApi().getSkills();
  const filter = vi.spyOn(result.data, "filter");
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const render = async (paused: Record<string, boolean>) =>
    act(async () =>
      root.render(
        <SkillGrid skills={result.data} paused={paused} night={false} onOpen={() => undefined} />,
      ),
    );
  await render({});
  const initial = filter.mock.calls.length;
  expect(initial).toBeGreaterThan(0);
  await render({ example: true });
  expect(filter.mock.calls.length).toBe(initial);
  await act(async () => root.unmount());
  host.remove();
});
