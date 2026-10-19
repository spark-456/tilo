// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { HttpClient } from "../../../api/http";
import { RoutinesPanel } from "./RoutinesPanel";
afterEach(cleanup);
const row = {
  schedule_id: "s /1",
  title: "Recorded routine",
  cadence: { weekday: 0, hour: 9, minute: 30, tz: "Asia/Kolkata" },
  enabled: true,
  next_due: "2026-10-12T04:00:00Z",
};
it("FR_AGT_14 Park lists real schedules and pauses only after the PATCH succeeds", async () => {
  const fetch = vi.fn(
    async (_url: RequestInfo | URL, init?: RequestInit) =>
      new Response(
        JSON.stringify(
          init?.method === "PATCH"
            ? { ...row, enabled: false, next_due: null }
            : { schedules: [row] },
        ),
      ),
  );
  let root: ReturnType<typeof mount> | undefined;
  await act(async () => {
    root = mount(<RoutinesPanel client={new HttpClient({ baseUrl: "https://api.test", fetch })} />);
  });
  if (!root) throw new Error("Panel missing");
  expect(root.container.textContent).toContain("Recorded routine");
  const pause = root.container.querySelector<HTMLButtonElement>('button[aria-label^="Pause "]');
  if (!pause) throw new Error("Pause missing");
  await act(async () => {
    pause.click();
  });
  expect(fetch.mock.calls.map((c) => c[0])).toEqual([
    "https://api.test/schedules",
    "https://api.test/schedules/s%20%2F1",
  ]);
  expect(JSON.parse(String(fetch.mock.calls[1]?.[1]?.body))).toEqual({ enabled: false });
  expect(root.container.textContent).toContain("Paused");
  expect(root.container.textContent).toContain("Resume");
  expect(root.container.querySelector("a")?.getAttribute("href")).toBe("/"); // SIMPLE-RUN-1: Home starts a run in one step; the old /start screen is not offered
});
it("FR_AGT_14 Park distinguishes an empty schedule list from a failure", async () => {
  for (const status of [200, 503]) {
    const client = new HttpClient({
      baseUrl: "https://api.test",
      fetch: async () => new Response(JSON.stringify({ schedules: [] }), { status }),
    });
    let root: ReturnType<typeof mount> | undefined;
    await act(async () => {
      root = mount(<RoutinesPanel client={client} />);
    });
    if (!root) throw new Error("Panel missing");
    expect(root.container.textContent).toContain(
      status === 200 ? "No routines yet" : "Could not load routines",
    );
    root.unmount();
  }
});
