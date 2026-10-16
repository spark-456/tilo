// TILO-T-WORLD: the names the world shows. A layout stored before districts were named for their work still says
// "Workstream 1"; it is shown as the name of the work its first unit building holds ("Find flights team"), which the
// layout itself records. Nothing is invented: with no unit building the stored name stays.
import type { Layout } from "@tilo/contracts";

type District = Layout["semantic"]["levels"][number]["districts"][number];

const GENERIC = /^Workstream \d+$/;

/** A district's display name: its own, unless it is the generic numbered one and a unit building says better. */
export function districtLabel(district: District): string {
  if (!GENERIC.test(district.name)) return district.name;
  const work = district.buildings.find((b) => b.plan_units.length > 0)?.name;
  if (!work) return district.name;
  const base = work.replace(/ \+\d+$/, "");
  return `${base.slice(0, 19)} team`.trim();
}
