// @vitest-environment happy-dom
// STUDIO-WIRE-1 (FR-AGT-14, FR-UX-10): the context panel's Future section lists routine next-run times from
// GET /schedules; forecasts stay unavailable.
import { act } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { createFixtureApi } from "../api/fixtureApi";
import { ParkProvider } from "../app/context";
import { ContextPanel } from "./ContextPanel";

afterEach(cleanup);
const settle = () => act(async () => undefined);
const view = (id: string, title: string, nextDue: string | null, enabled = true) => ({
  schedule_id: id,
  title,
  enabled,
  next_due: nextDue,
  cadence: { weekday: 0, hour: 9, minute: 0, tz: "Asia/Kolkata" },
});
const open = async (routines: { listSchedules: () => Promise<never[]> } | null) => {
  const m = mount(
    <ParkProvider api={createFixtureApi()}>
      <ContextPanel onClose={() => undefined} routines={routines as never} />
    </ParkProvider>,
  );
  await settle();
  return m.container.textContent ?? "";
};

it("FR_AGT_14_STUDIO_WIRE_1 routines list their next run from the schedules read", async () => {
  const text = await open({
    listSchedules: async () =>
      [
        view("a", "Monday digest", "2026-10-19T03:30:00Z"),
        view("b", "Paused sweep", null, false),
      ] as never[],
  });
  expect(text).toContain("Monday digest · Next run: Mon 19 Oct, 09:00");
  expect(text).toContain("Paused sweep · Next run: not scheduled");
  expect(text).toContain("Forecasts are not available yet.");
  expect(text).not.toContain("Routine next-run times and forecasts are not available");
});

it("FR_AGT_14_STUDIO_WIRE_1 no client or a failed read keeps the honest copy", async () => {
  for (const routines of [
    null,
    {
      listSchedules: () => Promise.reject(new Error("offline")),
    },
  ]) {
    const text = await open(routines);
    expect(text).toContain("Routine next-run times and forecasts are not available here yet.");
    cleanup();
  }
});

it("FR_AGT_14_STUDIO_WIRE_1 no routines yet says so", async () => {
  const text = await open({ listSchedules: async () => [] });
  expect(text).toContain("No routines yet.");
});
