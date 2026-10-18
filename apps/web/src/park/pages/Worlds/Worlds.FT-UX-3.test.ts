import { expect, it } from "vitest";
import type { World } from "../../api/types";
import { countFor, visibleWorlds } from "./model";

const world = (id: string, st: World["st"]): World => ({ id, name: id, st, tier: "Town" }) as World;

it("FT_UX_3 the Working chip counts the same worlds as the Working grid", () => {
  const worlds = [world("active", "running"), world("waiting", "needs")];
  expect(countFor(worlds, "", "all", "running")).toBe(1);
  expect(visibleWorlds(worlds, "", "all", "running").map((w) => w.id)).toEqual(["active"]);
});
