import { expect, it } from "vitest";
import { createMobileQuality } from "./mobileQuality";

it("FR_WLD_13_sustained_sub_30fps_mobile_motion_drops_agent_shadows", () => {
  const quality = createMobileQuality();
  for (let t = 0; t <= 1200; t += 50) quality.sample(t, 390);
  expect(quality.shadows).toBe(false);
  quality.sample(1250, 1440);
  expect(quality.shadows).toBe(true);
});

it("FR_WLD_13_desktop_and_healthy_mobile_keep_the_original_art", () => {
  for (const [width, frameMs] of [
    [1440, 50],
    [390, 16],
  ] as const) {
    const quality = createMobileQuality();
    for (let t = 0; t <= 1200; t += frameMs) quality.sample(t, width);
    expect(quality.shadows).toBe(true);
  }
});

it("FR_WLD_13_idle_gaps_and_invalid_times_cannot_trigger_a_quality_drop", () => {
  const quality = createMobileQuality();
  quality.sample(0, 390);
  quality.idle();
  quality.sample(10000, 390);
  quality.sample(Number.NaN, 390);
  quality.sample(Number.POSITIVE_INFINITY, 390);
  expect(quality.shadows).toBe(true);
});
