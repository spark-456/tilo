import { describe, expect, it } from "vitest";
import { matchFlowRoute } from "../router";
import { sectionOf } from "./PrimaryNav";
import { SCREENS } from "./meta";
import { matchScreen } from "./routes";

const FLOW_SCREENS = ["S-01", "S-02", "S-03", "S-04", "S-12"];

describe("PRD-18.3 AGW-08 route table: every Must screen has a route", () => {
  it("S-01..S-24 are all listed, and only the Should screens have no address", () => {
    expect(SCREENS.map((s) => s.id)).toEqual(
      Array.from({ length: 25 }, (_, i) => `S-${String(i + 1).padStart(2, "0")}`),
    );
    for (const s of SCREENS) expect(s.path === null).toBe(s.priority === "Should");
  });

  for (const s of SCREENS.filter((s) => s.path !== null)) {
    it(`${s.id} ${s.name} resolves from its own address`, () => {
      const path = s.path ?? "";
      if (FLOW_SCREENS.includes(s.id)) {
        expect(matchScreen(path)).toBeNull();
        if (s.id !== "S-01") expect(matchFlowRoute(path).screen).not.toBe("Start");
      } else {
        expect(matchScreen(path)?.id).toBe(s.id);
      }
    });
  }

  it("passes URL-decoded captures to the screen, and unknown paths belong to the flow shell", () => {
    expect(matchScreen("/world/w%201/inspect/B1")?.params).toEqual(["w 1", "B1"]);
    expect(matchScreen("/world/w%E0/inspect/B1")?.params).toEqual(["w%E0", "B1"]);
    expect(matchScreen("/nowhere")).toBeNull();
  });

  it("serves /more and, in dev, /screens", () => {
    expect(matchScreen("/more")?.id).toBe("more");
    expect(matchScreen("/screens")?.id).toBe("screens");
  });

  it("highlights one primary item per path, with More for everything else", () => {
    expect(sectionOf("/")).toBe("home");
    expect(sectionOf("/world/w1")).toBe("world");
    expect(sectionOf("/world/w1/delivery")).toBe("world");
    expect(sectionOf("/world/w1/trace")).toBe("story");
    expect(sectionOf("/needs-you/gate")).toBe("needs");
    expect(sectionOf("/library/artifacts")).toBe("library");
    expect(sectionOf("/autonomy")).toBe("more");
  });
});
