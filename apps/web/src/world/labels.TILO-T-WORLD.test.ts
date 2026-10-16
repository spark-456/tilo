/** TILO-T-WORLD step 6: building and district labels read as the plan's real unit titles, never "Workstream 1" when a
 * title exists (FR-WLD-04). A name the layout already made from the work is kept as it is. */
import type { Layout } from "@tilo/contracts";
import { expect, test } from "vitest";
import { villageBasicLayout } from "../../test-support/worldFixtures";
import { frameOf } from "./frame";
import { districtLabel } from "./labels";
import { createInitialState } from "./reducer";

type D = Parameters<typeof districtLabel>[0];
const district = (name: string, buildings: Array<{ name: string; units: string[] }>): D =>
  ({
    id: "D1",
    name,
    icon: "inbox",
    lead: "A_l1",
    buildings: buildings.map((b, i) => ({
      id: `B${i + 1}`,
      name: b.name,
      kind: "common",
      plan_units: b.units,
    })),
  }) as unknown as D;

test("FR-WLD-04 TILO-T-WORLD labels: a generic Workstream name is shown as the work its first unit building holds", () => {
  const d = district("Workstream 1", [
    { name: "Meeting Hall", units: [] },
    { name: "Find flights +2", units: ["U1", "U2", "U3"] },
  ]);
  expect(districtLabel(d)).toBe("Find flights team");
});

test("FR-WLD-04 TILO-T-WORLD labels: a name made from the work is kept, and a district with no unit building keeps its own", () => {
  expect(districtLabel(district("Book the hotel team", [{ name: "x", units: ["U1"] }]))).toBe(
    "Book the hotel team",
  );
  expect(districtLabel(district("Workstream 2", [{ name: "Meeting Hall", units: [] }]))).toBe(
    "Workstream 2",
  );
});

test("FR-WLD-04 TILO-T-WORLD labels: the stage frame uses the label for a generic district", () => {
  const layout = structuredClone(villageBasicLayout()) as unknown as Layout;
  const d = layout.semantic.levels[0]?.districts[0];
  if (!d) throw new Error("fixture has a district");
  d.name = "Workstream 1";
  const state = createInitialState(layout);
  const frame = frameOf(layout, state);
  const shown = frame.districts[0]?.name ?? "";
  expect(shown).not.toMatch(/^Workstream/);
});
