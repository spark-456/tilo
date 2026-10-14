// @vitest-environment happy-dom
// LIVE-HOME: a deployment whose Api serves who you are, the day, the costs and the worlds, but no calendar yet, still
// shows Home: the greeting, the numbers it has and the composer. No calendar means no events, not "Home data is unavailable".
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { mountHome, pageText, taskInput } from "../../../../test-support/park/homeHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import type { Api } from "../../api/index";
import { agendaFromPlate } from "../../api/live/agendaFromPlate";
import { NotBuilt } from "../../api/liveApi";

// LIVE-P2-B (66de32b4): the greeting follows the local hour, so the clock is pinned (09:00 local, any TZ) like the
// other Home tests; the gate ran at 14:28 UTC and got "Good afternoon".
beforeEach(() => vi.setSystemTime(new Date(2026, 8, 24, 9, 0)));
afterEach(() => {
  vi.useRealTimers();
  cleanup();
  vi.restoreAllMocks();
});

describe("LIVE-HOME Home without a calendar", () => {
  it("FR_UX_14 live plate summaries keep Home usable without invented calendar events", async () => {
    const api: Api = {
      ...createFixtureApi(),
      getAgenda: async () => ({
        data: agendaFromPlate({
          today: "2026-10-09",
          as_of: "2026-10-09T03:00:00Z",
          rows: [],
          parked: [],
          truncated: false,
        }),
        source: "live",
      }),
    };
    const { el } = await mountHome({ api });
    expect(pageText(el)).not.toContain("Home data is unavailable");
    expect(taskInput(el)).not.toBeNull();
    expect(el.querySelectorAll(".park-home-event")).toHaveLength(0);
  });
  it("LIVE-HOME Home shows the greeting and the composer when only the agenda is not built", async () => {
    const api: Api = {
      ...createFixtureApi(),
      getAgenda: () => Promise.reject(new NotBuilt("getAgenda")),
    };
    const { el } = await mountHome({ api });
    const text = pageText(el);
    expect(text).toMatch(/Good morning, \w+/);
    expect(text).not.toContain("Home data is unavailable");
    expect(taskInput(el)).not.toBeNull();
  });
});
