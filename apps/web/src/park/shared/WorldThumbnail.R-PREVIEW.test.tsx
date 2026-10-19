// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import village from "../../../../../contracts/fixtures/layout/valid/village_basic.json";
import type { HttpClient } from "../../api/http";
import type { World } from "../api/types";
import { WorldThumbnail, clearWorldThumbnailCache, layoutPlan } from "./WorldThumbnail";
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const world = (tier: World["tier"] = "Village", id = `w_${tier}`): World =>
  ({ id, name: tier, short: tier, tier }) as World;
afterEach(() => {
  clearWorldThumbnailCache();
  document.body.replaceChildren();
  vi.restoreAllMocks();
});
describe("R-PREVIEW static world card thumbnails", () => {
  it("R_PREVIEW_layout_plan_keeps_the_recorded_world_names_and_geometry", () => {
    const plan = layoutPlan(village as unknown as Parameters<typeof layoutPlan>[0]);
    expect(plan.districts[0]?.name).toBe("Mail");
    expect(plan.districts[0]?.buildings.map((building) => building.gen?.name)).toEqual([
      "Mail Room",
      "Reply Desk",
      "Town Hall",
      "Delivery Dock",
      "Agent Foundry",
    ]);
    expect(plan.districts[0]?.buildings[0]?.gen).toMatchObject({ fp: [2, 2], fl: 2 });
  });

  it("R_PREVIEW_world_without_a_layout_has_a_coloured_size_placeholder", () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    act(() => root.render(<WorldThumbnail world={world("Town")} client={null} night={false} />));
    expect(host.querySelector('[data-world-thumbnail="placeholder-town"]')).not.toBeNull();
    // P0-WORLDS-CARDS: replaced black cubes with soft gradient tile with initial and kind icon
    expect(host.querySelector(".park-worldthumb__tile")).not.toBeNull();
    expect(host.querySelector(".park-worldthumb__initial")?.textContent).toBe("T");
    expect(host.querySelector(".park-worldthumb__kind")).not.toBeNull();
    act(() => root.unmount());
  });

  it("R_PREVIEW_layout_read_and_picture_are_cached_across_cards", async () => {
    const getJson = vi.fn(async () => village);
    const client = { getJson } as unknown as HttpClient;
    const first = document.createElement("div");
    const second = document.createElement("div");
    document.body.append(first, second);
    const a = createRoot(first);
    const b = createRoot(second);
    await act(async () => {
      a.render(
        <WorldThumbnail
          world={world("Village", "w_village_basic")}
          client={client}
          night={false}
        />,
      );
      b.render(
        <WorldThumbnail
          world={world("Village", "w_village_basic")}
          client={client}
          night={false}
        />,
      );
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getJson).toHaveBeenCalledTimes(1);
    expect(first.querySelector('[data-world-thumbnail="layout"]')).not.toBeNull();
    expect(second.querySelector('[data-world-thumbnail="layout"]')).not.toBeNull();
    expect(first.innerHTML).toBe(second.innerHTML);
    act(() => {
      a.unmount();
      b.unmount();
    });
  });
});
