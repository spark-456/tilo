import { describe, expect, it } from "vitest";
import { clearPin } from "./pinClearance";

describe("UI_10_W14 measured city pin clearance", () => {
  const bounds = { left: 0, top: 96, right: 1440, bottom: 900 };
  const card = { left: 350, top: 410, right: 610, bottom: 460 };
  it("moves a card clear of a taller glass panel instead of clipping its button", () => {
    const panel = { left: 24, top: 96, right: 524, bottom: 550 };
    // No room below the panel: the nearest clear position must be alongside it.
    const next = clearPin(card, { ...bounds, bottom: 550 }, [panel]);
    expect(next).toEqual({ x: 182, y: 0 });
    expect(card.left + (next?.x ?? 0)).toBeGreaterThan(panel.right);
  });
  it("keeps a clear card at its city position", () => {
    expect(clearPin(card, bounds, [])).toEqual({ x: 0, y: 0 });
  });
  it("keeps the whole card in bounds and clear of adjacent cards", () => {
    const next = clearPin(
      { left: 1350, top: 100, right: 1610, bottom: 150 },
      { ...bounds, bottom: 400 },
      [{ left: 1150, top: 96, right: 1440, bottom: 400 }],
    );
    expect(next).toEqual({ x: -468, y: 0 });
  });
  it("omits the pin when panels leave no clear space", () => {
    expect(clearPin(card, bounds, [bounds])).toBeNull();
  });
});
