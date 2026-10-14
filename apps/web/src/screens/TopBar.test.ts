import { describe, expect, it } from "vitest";
import { placeOf } from "./TopBar";
import { SCREENS } from "./meta";

describe("UX-227-C the top bar's current place", () => {
  it("names Home, a new task step and a lens of a world from the address alone", () => {
    expect(placeOf("/")).toEqual({ name: "Home", sub: null, world: null });
    expect(placeOf("/world/w_a/stage")).toEqual({ name: "World", sub: null, world: "w_a" });
    expect(placeOf("/world/w_a/story")).toEqual({ name: "World", sub: "Story", world: "w_a" });
    expect(placeOf("/world/w_a/delivery").sub).toBe("Delivery");
  });

  it("a ?fixture= replay is the world at any address, and an unknown path is Not found", () => {
    expect(placeOf("/", true).name).toBe("World");
    expect(placeOf("/world/w_a/nonsense").name).toBe("Not found");
  });

  it("every built screen has a place name that is short (never a sentence)", () => {
    for (const s of SCREENS.filter((m) => m.path !== null && m.status === "built")) {
      const name = placeOf(s.path ?? "").name;
      expect(name.length, `${s.id}: ${name}`).toBeGreaterThan(0);
      expect(name.length, `${s.id}: ${name}`).toBeLessThanOrEqual(40);
    }
  });
});
