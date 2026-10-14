// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { TiloApiError } from "../../../api/http";
import { RoutinesPanel } from "./RoutinesPanel";
afterEach(cleanup);
it("NFR22 Routines Retry refreshes after an uncertain write without resubmitting PATCH", async () => {
  const row = {
    schedule_id: "s_1",
    title: "Routine",
    cadence: { weekday: 0, hour: 9, minute: 0, tz: "UTC" },
    enabled: true,
    next_due: null,
  };
  const client = {
    listSchedules: vi.fn().mockResolvedValue([row]),
    updateSchedule: vi.fn().mockRejectedValue(new TiloApiError("rate_limited", 429, true, true)),
  };
  let root: ReturnType<typeof mount> | undefined;
  await act(async () => {
    root = mount(<RoutinesPanel client={client} />);
  });
  if (!root) throw new Error("Routines did not mount");
  const view = root;
  await act(async () => {
    view.container
      .querySelector("article button")
      ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  expect(view.container.textContent).toContain("Too many requests. Wait a moment and try again.");
  const box = view.container.querySelector<HTMLElement>("[data-api-read-state]");
  expect(box?.style.blockSize).toBe("176px");
  await act(async () => {
    box?.querySelector("button")?.click();
  });
  expect(client.listSchedules).toHaveBeenCalledTimes(2);
  expect(client.updateSchedule).toHaveBeenCalledTimes(1);
});
