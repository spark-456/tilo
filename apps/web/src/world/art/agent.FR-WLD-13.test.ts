// @vitest-environment happy-dom
import { Graphics } from "pixi.js";
import { expect, it, vi } from "vitest";
import { drawAgent } from "./agent";

it("FR_WLD_13_lean_art_removes_the_shadow_but_still_draws_the_agent", () => {
  const full = new Graphics();
  const lean = new Graphics();
  const fullShadow = vi.spyOn(full, "ellipse");
  const leanShadow = vi.spyOn(lean, "ellipse");
  drawAgent(full, "specialist", "#112233");
  drawAgent(lean, "specialist", "#112233", false);
  expect(fullShadow).toHaveBeenCalledTimes(1);
  expect(leanShadow).not.toHaveBeenCalled();
  expect(lean.getBounds().width).toBeGreaterThan(0);
  full.destroy();
  lean.destroy();
});
