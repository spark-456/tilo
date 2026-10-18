// @vitest-environment happy-dom
// P0-WORLDS-CARDS acceptance:
// The Worlds cards show random black cube placeholders on grey diamond art with "Village" labels; it ruins the feel.
// Replace with a clean, branded card: status chip, title (2 lines), progress, agents count, last update,
// and a small tasteful thumbnail rendered from the real layout (R-PREVIEW) or, when there is none,
// a soft gradient tile with the world's initial and kind icon. No black cubes, no empty "Village" text.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { card, renderWorlds, worldsApi } from "../../../../test-support/park/worldsHarness";
import type { World } from "../../api/types";

afterEach(cleanup);

const text = (el: Element | null) => el?.textContent ?? "";

const liveItem = (id: string, name: string, extra: Partial<World> = {}): World => ({
  id,
  name,
  short: name,
  tier: "Village",
  tool: "",
  st: "running",
  agents: 0,
  spend: "",
  spendV: 0,
  nextL: "",
  nextV: "",
  owner: "",
  started: "2026-10-18T10:00:00Z",
  ...extra,
});

describe("P0-WORLDS-CARDS: clean, branded cards without black cubes or empty Village text", () => {
  it("test_P0_WORLDS_CARDS_no_black_cubes_and_renders_soft_gradient_tile_with_initial_and_icon", async () => {
    const api = worldsApi(() => [liveItem("w_live_1", "Plan the offsite")]);
    const { c } = await renderWorlds({ api });
    const el = card(c, "w_live_1");
    expect(el).not.toBeNull();

    // No black cubes or grey diamond ground
    expect(el?.querySelectorAll(".park-worldthumb__block")).toHaveLength(0);
    expect(el?.querySelector(".park-worldthumb__ground")).toBeNull();

    // Renders soft gradient tile with world's initial and kind icon
    const tile = el?.querySelector(".park-worldthumb__tile");
    expect(tile, "gradient tile exists").not.toBeNull();
    const initial = el?.querySelector(".park-worldthumb__initial");
    expect(initial?.textContent?.trim()).toBe("P");
    const kind = el?.querySelector(".park-worldthumb__kind");
    expect(kind, "kind icon exists").not.toBeNull();
    expect(kind?.querySelector("svg")).not.toBeNull();
  });

  it("test_P0_WORLDS_CARDS_no_empty_village_label_when_zero_agents", async () => {
    const api = worldsApi(() => [liveItem("w_live_1", "Plan the offsite", { agents: 0 })]);
    const { c } = await renderWorlds({ api });
    const el = card(c, "w_live_1");
    expect(el).not.toBeNull();

    // Must not print bare "Village" text anywhere in the footer or body
    const foot = el?.querySelector(".park-worlds-card__foot");
    expect(text(foot)).not.toContain("Village");

    // Title and status chip are present
    expect(text(el)).toContain("Plan the offsite");
    const chip = el?.querySelector(".park-worlds-chip");
    expect(chip).not.toBeNull();
  });

  it("test_P0_WORLDS_CARDS_shows_agents_count_when_greater_than_zero", async () => {
    const api = worldsApi(() => [liveItem("w_live_2", "Security review", { agents: 3 })]);
    const { c } = await renderWorlds({ api });
    const el = card(c, "w_live_2");
    expect(el).not.toBeNull();

    const foot = el?.querySelector(".park-worlds-card__foot");
    expect(text(foot)).toContain("3 helpers");
  });
});
