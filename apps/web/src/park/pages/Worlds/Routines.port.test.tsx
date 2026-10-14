// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { TiloApiError } from "../../../api/http";
import { RoutinesPanel } from "./RoutinesPanel";
afterEach(cleanup);
const row = {
  schedule_id: "a",
  title: "Weekly scan",
  enabled: true,
  cadence: { weekday: 0, hour: 9, minute: 0, tz: "UTC" },
  next_due: null,
};
const button = (root: HTMLElement, name: string) => {
  const found = [...root.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === name,
  );
  if (!found) throw new Error(`Missing ${name}`);
  return found;
};
it("FR_MTG_08 OLDUI5 delete requires confirmation and Retry never repeats an uncertain DELETE", async () => {
  const client = {
    listSchedules: vi.fn().mockResolvedValue([row]),
    updateSchedule: vi.fn(),
    deleteSchedule: vi.fn().mockRejectedValue(new TiloApiError("rate_limited", 429, true, true)),
  };
  let view: ReturnType<typeof mount> | undefined;
  await act(async () => {
    view = mount(<RoutinesPanel client={client} />);
  });
  if (!view) throw new Error("Panel missing");
  const root = view.container;
  await act(async () => {
    button(root, "Delete").click();
  });
  expect(client.deleteSchedule).not.toHaveBeenCalled();
  expect(document.activeElement).toBe(button(root, "Keep routine"));
  await act(async () => {
    button(root, "Delete routine").click();
    button(root, "Delete routine").click();
  });
  expect(client.deleteSchedule).toHaveBeenCalledTimes(1);
  expect(root.textContent).toContain("Weekly scan");
  expect(root.textContent).toContain("Too many requests");
  await act(async () => {
    button(root, "Retry").click();
  });
  expect(client.listSchedules).toHaveBeenCalledTimes(2);
  expect(client.deleteSchedule).toHaveBeenCalledTimes(1);
});
it("FR_MTG_08 OLDUI5 successful delete removes only the acknowledged row", async () => {
  let resolve!: () => void;
  const client = {
    listSchedules: vi.fn().mockResolvedValue([row]),
    updateSchedule: vi.fn(),
    deleteSchedule: vi.fn(
      () =>
        new Promise<void>((done) => {
          resolve = done;
        }),
    ),
  };
  let view: ReturnType<typeof mount> | undefined;
  await act(async () => {
    view = mount(<RoutinesPanel client={client} />);
  });
  if (!view) throw new Error("Panel missing");
  const root = view.container;
  await act(async () => {
    button(root, "Delete").click();
  });
  await act(async () => {
    button(root, "Delete routine").click();
  });
  expect(root.textContent).toContain("Weekly scan");
  expect(button(root, "Delete routine").disabled).toBe(true);
  await act(async () => {
    resolve();
  });
  expect(root.textContent).toContain("No routines yet.");
  expect(client.deleteSchedule).toHaveBeenCalledWith("a");
});
