// @vitest-environment happy-dom
// WEB-6 acceptance: the responsive rule of the World page (reference `topCols`):
//   grid-template-columns: (app.vw || 1440) >= 1060 ? 'minmax(0,1.7fr) minmax(300px,1fr)' : 'minmax(0,1fr)'
// The columns depend on the app's viewport width, which only JavaScript knows, so the top grid sets them
// inline. The lower grid (`repeat(auto-fit, minmax(min(100%, 420px), 1fr))`) and the 440px map are pinned in
// World.styles.test.ts and measured in the browser by e2e/park-world.spec.ts.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { K1 } from "../../../../test-support/park/worldCopy";
import { mountWorld, topGridColumns } from "../../../../test-support/park/worldHarness";

afterEach(cleanup);

const WIDE = "minmax(0,1.7fr)minmax(300px,1fr)";
const ONE = "minmax(0,1fr)";

describe("WEB_6_world_layout: the top grid", () => {
  it.each([
    [1440, WIDE],
    [1200, WIDE],
    [1061, WIDE],
    [1060, WIDE],
    [1059, ONE],
    [760, ONE],
    [390, ONE],
  ] as const)("WEB_6_world_layout_the_top_grid_at_vw_%i", async (vw, want) => {
    const { el } = await mountWorld({ app: { vw } });
    expect(topGridColumns(el, K1.heroTag)).toBe(want);
  });

  it("WEB_6_world_layout_a_missing_width_counts_as_1440_like_the_reference", async () => {
    const { el } = await mountWorld({ app: { vw: 0 } });
    expect(topGridColumns(el, K1.heroTag)).toBe(WIDE);
  });

  it("WEB_6_world_layout_the_columns_follow_a_resize_of_the_mounted_page", async () => {
    const rig = await mountWorld();
    expect(topGridColumns(rig.el, K1.heroTag)).toBe(WIDE);
    await rig.update({ vw: 390 });
    expect(topGridColumns(rig.el, K1.heroTag)).toBe(ONE);
    await rig.update({ vw: 1440 });
    expect(topGridColumns(rig.el, K1.heroTag)).toBe(WIDE);
  });

  it("WEB_6_world_layout_the_Town_and_Village_top_grids_follow_the_same_rule", async () => {
    for (const id of ["northline", "calls"]) {
      const wide = await mountWorld({ id, app: { vw: 1440 } });
      const tag = id === "northline" ? "Small project · 7 agents" : "Quick task · 1 agent";
      expect(topGridColumns(wide.el, tag)).toBe(WIDE);
      cleanup();
      const narrow = await mountWorld({ id, app: { vw: 390 } });
      expect(topGridColumns(narrow.el, tag)).toBe(ONE);
      cleanup();
    }
  });
});
