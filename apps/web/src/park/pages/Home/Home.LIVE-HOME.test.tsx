// @vitest-environment happy-dom
// LIVE-HOME: a deployment whose Api serves who you are, the day, the costs and the worlds, but no calendar yet, still
// shows Home: the greeting, the numbers it has and the composer. No calendar means no events, not "Not connected yet".
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { mountHome, pageText, taskInput } from "../../../../test-support/park/homeHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import type { Api } from "../../api/index";
import { agendaFromPlate } from "../../api/live/agendaFromPlate";
import { NotBuilt } from "../../api/liveApi";

afterEach(() => {
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
    expect(pageText(el)).not.toContain("Not connected yet");
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
    expect(text).toMatch(/Good (morning|evening), \w+/);
    expect(text).not.toContain("Not connected yet");
    expect(taskInput(el)).not.toBeNull();
  });
});
