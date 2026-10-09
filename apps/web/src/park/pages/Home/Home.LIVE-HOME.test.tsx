// @vitest-environment happy-dom
// LIVE-HOME: a deployment whose Api serves who you are, the day, the costs and the worlds, but no calendar yet, still
// shows Home: the greeting, the numbers it has and the composer. No calendar means no events, not "Not connected yet".
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { mountHome, pageText, taskInput } from "../../../../test-support/park/homeHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import type { Api } from "../../api/index";
import { NotBuilt } from "../../api/liveApi";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("LIVE-HOME Home without a calendar", () => {
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
