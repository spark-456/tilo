// How a building looks, from what the layout says it is. The common types map to the prototype's
// kit table (design/source/tilo-world.js KIT: roof and facade per building, ADR-0003); a kit
// building has no fixed look, so one is picked from its id, the same every time.
import type { LayoutBuilding } from "@tilo/contracts";
import type { Facade, Roof } from "./building";
import { hash } from "./color";

type Look = readonly [Roof, Facade];

const COMMON: Readonly<Record<string, Look>> = {
  town_hall: ["dome", "arches"],
  your_desk: ["gable", "windows"],
  library: ["gable", "arches"],
  browser_station: ["flat", "band"],
  workshop: ["gable", "windows"],
  meeting_hall: ["dome", "arches"],
  connector_post: ["flat", "band"],
  memory_vault: ["dome", "windows"],
  treasury: ["dome", "arches"],
  watchtower: ["gable", "windows"],
  delivery_dock: ["flat", "windows"],
  clock_tower: ["dome", "arches"],
  agent_foundry: ["flat", "band"],
  mail_room: ["gable", "windows"],
  expert_office: ["flat", "band"],
};
const ROOFS: readonly Roof[] = ["flat", "gable", "dome"];
const FACADES: readonly Facade[] = ["windows", "band", "arches"];

export function styleOf(b: Pick<LayoutBuilding, "id" | "common_type">): {
  roof: Roof;
  facade: Facade;
} {
  const known = b.common_type ? COMMON[b.common_type] : undefined;
  const h = hash(b.id);
  const [roof, facade] = known ?? [ROOFS[h % 3] as Roof, FACADES[(h >>> 4) % 3] as Facade];
  return { roof, facade };
}
