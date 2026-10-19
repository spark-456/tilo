// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click } from "../../../../test-support/park/componentsHarness";
import {
  liveSourced,
  mountLiveHome,
  serverWorld,
} from "../../../../test-support/park/liveHomeHarness";
import { worldsFromList } from "../../api/live/worldsFromList";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("P0_RESULTS on Home", () => {
  it("P0_RESULTS_only_completed_live_worlds_enter_the_latest_results_strip", () => {
    const worlds = worldsFromList([
      {
        world_id: "done",
        title: "Final budget",
        status: "completed",
        created_at: "2026-10-19T10:00:00Z",
        last_seq: 5,
      },
      {
        world_id: "failed",
        title: "Failed search",
        status: "failed",
        created_at: "2026-10-19T11:00:00Z",
        last_seq: 6,
      },
    ]);
    expect(worlds[0]?.resultReady).toBe(true);
    expect(worlds[1]?.resultReady).toBe(false);
  });

  it("P0_RESULTS_home_links_to_real_completed_results_only", async () => {
    const finished = {
      ...serverWorld("workspace", "Final budget", "w_done"),
      st: "finished" as const,
      isNew: false,
      resultReady: true,
    };
    const failed = {
      ...serverWorld("workspace", "Failed search", "w_failed"),
      st: "finished" as const,
      isNew: false,
      resultReady: false,
    };
    const api = liveSourced({
      getWorlds: vi.fn(async () => ({ data: [failed, finished], source: "live" as const })),
    });
    const rig = await mountLiveHome(api);
    const strip = rig.el.querySelector('section[aria-label="Latest results"]');
    expect(strip?.textContent).toContain("Final budget");
    expect(strip?.textContent).not.toContain("Failed search");
    const link = [...(strip?.querySelectorAll("button") ?? [])].find((button) =>
      button.textContent?.includes("Final budget"),
    );
    expect(link).toBeDefined();
    click(link as HTMLButtonElement);
    expect(rig.navigate).toHaveBeenCalled();
  });
});
