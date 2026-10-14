import { describe, expect, it } from "vitest";
import { ALL_ROUTES } from "../../e2e/support/routes";
import { isParkPath } from "../park/app/router";
import { matchFlowRoute } from "../router";
import { parseViewPath } from "../worldView/routes";
import { sectionOf } from "./PrimaryNav";
import { SCREENS } from "./meta";
import { matchScreen } from "./routes";

const FLOW_SCREENS = ["S-04"];
const PARK_VIEWS = ["S-05", "S-06", "S-07", "S-08", "S-10", "S-11", "S-12"];

describe("PRD-18.3 AGW-08 route table: every Must screen has a route", () => {
  it("the rows are S-01..S-29 minus the screens OLD-UI-OUT 3 moved to Park, and only the Should screens have no address", () => {
    const moved = new Set(["S-01", "S-02", "S-03", "S-09", "S-13", "S-14", "S-21", "S-26", "S-27", "S-28", "S-29"]);
    expect(SCREENS.map((s) => s.id)).toEqual(
      Array.from({ length: 29 }, (_, i) => `S-${String(i + 1).padStart(2, "0")}`).filter(
        (id) => !moved.has(id),
      ),
    );
    for (const s of SCREENS) expect(s.path === null).toBe(s.priority === "Should");
  });

  for (const s of SCREENS.filter((s) => s.path !== null)) {
    it(`${s.id} ${s.name} resolves from its own address`, () => {
      const path = s.path ?? "";
      if (["S-17", "S-18", "S-19"].includes(s.id)) {
        expect(isParkPath(path)).toBe(true);
        expect(matchScreen(path)).toBeNull();
      } else if (FLOW_SCREENS.includes(s.id)) {
        expect(matchScreen(path)).toBeNull();
        expect(matchFlowRoute(path).screen).not.toBe("Start");
      } else if (PARK_VIEWS.includes(s.id)) {
        expect(parseViewPath(path), path).not.toBeNull();
        expect(matchScreen(path)?.id).not.toBe(s.id);
      } else {
        expect(matchScreen(path)?.id).toBe(s.id);
      }
    });
  }

  it("FR-WLD-11: the accessibility sweep's route list holds every screen address", () => {
    const missing = SCREENS.flatMap((s) => (s.path === null ? [] : [s.path])).filter(
      (path) => !ALL_ROUTES.includes(path),
    );
    expect(missing).toEqual([]);
  });

  it("passes URL-decoded captures to the screen, and unknown paths belong to the flow shell", () => {
    expect(matchScreen("/meetings/m%201")?.params).toEqual(["m 1"]);
    expect(matchScreen("/meetings/m%E0")?.params).toEqual(["m%E0"]);
    expect(matchScreen("/nowhere")).toBeNull();
  });

  it("UX_1 a path under /world/ or /task/ that no screen owns is Not found, never Start", () => {
    for (const path of [
      "/world/w/inspect/B1/x",
      "/world/w/inspect/B1//",
      "/world/w/inspect",
      "/world/w/unknown",
      "/world/",
      "/task/t/unknown",
      "/world/%E0/x",
    ]) {
      expect(matchScreen(path)?.id, path).toBe("not-found");
    }
    // Real addresses are untouched: the flow shell and every screen keep theirs.
    expect(parseViewPath("/world/w/inspect/B1")?.kind).toBe("inspect");
    expect(parseViewPath("/world/w/delivery")).toEqual({
      kind: "lens",
      worldId: "w",
      lens: "delivery",
    });
    expect(matchScreen("/world/w/stage")).toBeNull(); // the stage is a flow route (S-04)
    expect(matchScreen("/task/t/approaches")?.id).toBe("not-found"); // retired: Root sends it Home first
    expect(matchScreen("/nowhere")).toBeNull();
  });

  it("serves /more and, in dev, /screens", () => {
    expect(isParkPath("/more")).toBe(true);
    expect(matchScreen("/more")).toBeNull();
    expect(matchScreen("/screens")?.id).toBe("screens");
  });

  it("highlights one primary item per path, with More for everything else", () => {
    expect(sectionOf("/")).toBe("home");
    expect(sectionOf("/world/w1")).toBe("world");
    expect(sectionOf("/world/w1/delivery")).toBe("world");
    expect(sectionOf("/world/w1/trace")).toBe("story");
    expect(sectionOf("/needs-you/gate")).toBe("needs");
    expect(sectionOf("/autonomy")).toBe("more");
    expect(sectionOf("/world/w1/stage")).toBe("world"); // S-04 (WEB-CUTOVER: /world/:id is the Park overview)
  });
});
