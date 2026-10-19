// UI-STUDIO-INT: happy-dom's window is 1024 px wide, where the eight nav tabs no longer all fit (some sit in the More
// menu). A test about the full desktop tab strip makes the window 1440 x 900 for itself; it goes back after the test.
import { onTestFinished } from "vitest";

type HappyWindow = { happyDOM: { setViewport(v: { width: number; height: number }): void } };

export function wideWindow(): void {
  const hd = (window as unknown as HappyWindow).happyDOM;
  const before = { width: window.innerWidth, height: window.innerHeight };
  hd.setViewport({ width: 1440, height: 900 });
  onTestFinished(() => hd.setViewport(before));
}
