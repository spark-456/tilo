// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from "vitest";
import { getDensity, initDensity, setDensity } from "./density";

describe("FR-WLD-14 UX-1 density mode is a display setting, applied live and remembered", () => {
  beforeEach(() => {
    window.localStorage.clear();
    initDensity();
  });

  it("starts Friendly and writes the mode to <html>", () => {
    expect(getDensity()).toBe("friendly");
    expect(document.documentElement.dataset.density).toBe("friendly");
  });

  it("switching applies at once and survives a reload", () => {
    setDensity("professional");
    expect(document.documentElement.dataset.density).toBe("professional");
    expect(window.localStorage.getItem("tilo.density")).toBe("professional");
    initDensity(); // a reload
    expect(getDensity()).toBe("professional");
  });

  it("an unknown stored value is the default look", () => {
    window.localStorage.setItem("tilo.density", "compact");
    initDensity();
    expect(getDensity()).toBe("friendly");
  });

  it("still applies for this visit when storage refuses", () => {
    const set = window.localStorage.setItem.bind(window.localStorage);
    window.localStorage.setItem = () => {
      throw new Error("blocked");
    };
    expect(() => setDensity("professional")).not.toThrow();
    expect(getDensity()).toBe("professional");
    window.localStorage.setItem = set;
  });
});
