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

  it("maps /world/:worldId to World", () => {
    expect(matchFlowRoute("/world/abc")).toEqual({
      screen: "World",
      worldId: "abc",
    });
  });

  it("maps /world/:worldId/delivery to Delivery", () => {
    expect(matchFlowRoute("/world/abc/delivery")).toEqual({
      screen: "Delivery",
      worldId: "abc",
    });
  });

  it("maps unknown paths to Start", () => {
    expect(matchFlowRoute("/unknown/path/here")).toEqual({ screen: "Start" });
  });
});
