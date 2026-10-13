// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, q, qa } from "../../../test-support/park/componentsHarness";
import { mountApp } from "../../../test-support/park/shellHarness";
import { createLiveApi } from "../api/liveApi";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);
afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});
const bell = () => q<HTMLButtonElement>(document.body, 'button[aria-label="Notifications"]');
const dialog = () => q<HTMLElement>(document.body, '[role="dialog"][aria-label="Notifications"]');
const liveApi = (body: unknown, status = 200) =>
  createLiveApi({
    baseUrl: "https://api.example.test",
    fetch: vi.fn(
      async (url) =>
        new Response(
          JSON.stringify(
            String(url).includes("/v1/notifications") ? body : { cards: [], next_cursor: null },
          ),
          { status },
        ),
    ),
  });

describe("FR_UX_11 live bell", () => {
  it("FR_UX_11_done_item_shows_unread_and_opens_its_real_world", async () => {
    const { navigate } = await mountApp({
      api: liveApi({
        notifications: [
          {
            id: "e:one",
            kind: "done",
            created_at: "2026-10-09T10:00:00Z",
            world_id: "world-one",
            title: "An item is ready",
            card_id: null,
            artifact_id: null,
          },
        ],
        count: 1,
      }),
    });
    expect([...bell().children].filter((c) => c.tagName.toLowerCase() !== "svg")).toHaveLength(1);
    click(bell());
    const row = q<HTMLButtonElement>(dialog(), "button[data-kind]");
    expect(row.textContent).toBe("An item is ready2026-10-09T10:00:00Z");
    click(row);
    // A real world absent from the demo world list navigates directly.
    expect(navigate).toHaveBeenCalledWith("/world/world-one");
  });
  it("FR_UX_11_empty_bell_says_no_notifications", async () => {
    await mountApp({ api: liveApi({ notifications: [], count: 0 }) });
    click(bell());
    expect(dialog().textContent).toContain("No notifications yet");
    expect(qa(dialog(), "button[data-kind]")).toHaveLength(0);
  });
  it("FR_UX_11_failed_bell_says_unavailable_instead_of_empty", async () => {
    await mountApp({ api: liveApi({ detail: "unavailable" }, 503) });
    click(bell());
    expect(dialog().textContent).toContain("Notifications are unavailable. Try again later.");
    expect(dialog().textContent).not.toContain("No notifications yet");
  });
});
