// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";
import { cleanup, mount, qa } from "../../../../test-support/park/componentsHarness";
import { ledger } from "../../api/fixtures";
import { SpendChart } from "./SpendChart";
import { chartGeometry, hasChart, money } from "./model";

afterEach(cleanup);

it("W25_UI_10_chart_annotations_are_outside_the_dashed_plot", () => {
  const { container } = mount(<SpendChart L={ledger} dec={{}} />);
  const notes = qa(container, ".park-ledger-note");
  expect(notes.length).toBe(3);
  for (const note of notes) {
    expect(note.closest(".park-ledger-chart")).toBeNull();
    expect(note.parentElement?.className).toBe("park-ledger-notes");
  }
});

it("W25_UI_10_forecast_without_pending_cost_does_not_invent_an_approval", () => {
  const L = { ...ledger, currency: "USD" as const, tx: [] };
  expect(chartGeometry(L, {}, null).fcLabel).toBe("Forecast $6,300");
  expect(money(L, 1234.5)).toBe("$1,235");
  expect(hasChart({ ...L, daily: [] })).toBe(false);
  expect(hasChart({ ...L, budget: 0 })).toBe(false);
});
