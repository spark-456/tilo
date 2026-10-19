// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { mountWorld, pageText, spiedApi } from "../../../../test-support/park/worldHarness";
afterEach(cleanup);
it("LIVE-MEETHOST World shows one not-connected line alongside its other gaps", async () => {
  const api = spiedApi();
  api.getConnectors = vi.fn(async () => ({
    source: "live" as const,
    data: [
      {
        id: "meeting_host",
        name: "Host",
        cat: "",
        mono: "M",
        col: "",
        st: "available" as const,
        live: { stateKnown: false, scopes: [], notConfigured: true },
      },
    ],
  }));
  api.getSkills = vi.fn(async () => {
    throw new Error("unavailable");
  });
  const { el } = await mountWorld({ api });
  expect(pageText(el).split("Meeting host is not connected yet")).toHaveLength(2);
  expect(pageText(el)).toContain("Skills");
  expect(pageText(el)).toContain("Not available yet");
});
