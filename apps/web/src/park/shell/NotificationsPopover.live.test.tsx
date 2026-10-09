// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, q } from "../../../test-support/park/componentsHarness";
import { mountApp } from "../../../test-support/park/shellHarness";
import { TiloApiError } from "../../api/http";
import { NotBuilt, createLiveApi } from "../api/liveApi";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);
afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});
it("FR_UX_11 live bell shows the real response and opens its world", async () => {
  const fetch = vi.fn(
    async (url: RequestInfo | URL) =>
      new Response(
        JSON.stringify(
          String(url).includes("notifications")
            ? {
                count: 1,
                notifications: [
                  {
                    id: "e:actual",
                    kind: "done",
                    created_at: "2026-10-09T10:00:00Z",
                    world_id: "actual-world",
                    title: "An item is ready",
                    card_id: null,
                    artifact_id: "art_actual",
                  },
                ],
              }
            : { cards: [], next_cursor: null },
        ),
      ),
  );
  const { navigate } = await mountApp({
    api: createLiveApi({ baseUrl: "https://api.test", fetch }),
  });
  expect(fetch.mock.calls.map(([url]) => String(url))).toContain(
    "https://api.test/v1/notifications?limit=100",
  );
  click(q(document.body, 'button[aria-label="Notifications"]'));
  const dialog = q(document.body, '[role="dialog"][aria-label="Notifications"]');
  expect(dialog.textContent).toContain("An item is ready");
  expect(dialog.textContent).toContain("2026-10-09T10:00:00Z");
  expect(dialog.textContent).not.toMatch(/K1 electric|Northline|HubSpot|£/);
  click(q(dialog, 'button[data-kind="done"]'));
  expect(navigate).toHaveBeenCalledWith("/world/actual-world");
});
it("FR_UX_11 unavailable, malformed and empty responses never return fixture notifications", async () => {
  await expect(createLiveApi().getNotifications()).rejects.toBeInstanceOf(NotBuilt);
  const api = (body: unknown, status = 200) =>
    createLiveApi({
      baseUrl: "https://api.test",
      fetch: async () => new Response(JSON.stringify(body), { status }),
    });
  await expect(api({ count: 0, notifications: [] }).getNotifications()).resolves.toEqual({
    source: "live",
    data: [],
  });
  await expect(api({ notifications: [] }).getNotifications()).rejects.toBeInstanceOf(TiloApiError);
  await expect(api({}, 503).getNotifications()).rejects.toBeInstanceOf(TiloApiError);
});
