// @vitest-environment happy-dom
// UI-STUDIO-5: the scene preference is display state in browser storage, shared with the Chat scene (UI-STUDIO-2).
import { afterEach, describe, expect, it, vi } from "vitest";
import { SCENE_IDS, SCENE_KEY, getScene, setScene } from "./scenePref";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("STUDIO_5 scenePref", () => {
  it("STUDIO_5 scene ids are the four scenes and the default is the office", () => {
    expect([...SCENE_IDS]).toEqual(["office", "balcony", "beach", "cosy"]);
    expect(getScene()).toBe("office");
  });

  it("STUDIO_5 scene round trips each id and reads Chat's own words", () => {
    for (const id of SCENE_IDS) {
      setScene(id);
      expect(getScene()).toBe(id);
    }
    window.localStorage.setItem(SCENE_KEY, "room");
    expect(getScene()).toBe("cosy");
    window.localStorage.setItem(SCENE_KEY, "volcano");
    expect(getScene()).toBe("office");
  });

  it("STUDIO_5 scene blocked storage never throws and falls back to the office", () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => setScene("beach")).not.toThrow();
    expect(getScene()).toBe("office");
  });
});
