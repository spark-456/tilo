import { describe, expect, it } from "vitest";
import { matchFlowRoute } from "./router";

describe("PRD-18.3 flow: the router maps each flow path to its screen and unknown paths to Start", () => {
  it("maps / to Start", () => {
    expect(matchFlowRoute("/")).toEqual({ screen: "Start" });
  });

  it("maps /task/:taskId/understanding to Understanding", () => {
    expect(matchFlowRoute("/task/123/understanding")).toEqual({
      screen: "Understanding",
      taskId: "123",
    });
  });

  it("maps /task/:taskId/approaches to Approaches", () => {
    expect(matchFlowRoute("/task/123/approaches")).toEqual({
      screen: "Approaches",
      taskId: "123",
    });
  });

  it("maps /world/:worldId/stage to World", () => {
    expect(matchFlowRoute("/world/abc/stage")).toEqual({
      screen: "World",
      worldId: "abc",
    });
  });

  it("leaves /world/:worldId/delivery to S-12 (routes.tsx), so the flow shell has no Delivery", () => {
    expect(matchFlowRoute("/world/abc/delivery")).toEqual({ screen: "Start" });
  });

  it("maps unknown paths to Start", () => {
    expect(matchFlowRoute("/unknown/path/here")).toEqual({ screen: "Start" });
  });

  it("maps a malformed percent escape to Start instead of throwing", () => {
    for (const path of [
      "/task/%E0/understanding",
      "/task/%/approaches",
      "/world/%E0%A4%A/stage",
      "/world/%E0/stage",
      "/world/%E0/delivery",
    ]) {
      expect(matchFlowRoute(path)).toEqual({ screen: "Start" });
    }
  });

  it("decodes a well-formed escape", () => {
    expect(matchFlowRoute("/world/a%20b/stage")).toEqual({ screen: "World", worldId: "a b" });
  });
});
