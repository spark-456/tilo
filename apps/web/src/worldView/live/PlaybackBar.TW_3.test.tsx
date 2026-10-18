// @vitest-environment happy-dom
import type { Layout } from "@tilo/contracts";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../test-support/park/componentsHarness";
import { villageBasicLayout } from "../../../test-support/worldFixtures";
import { ev, fakeWorld, resetEvents, withClient } from "../../../test-support/worldLive";
import { getReplayPoint, setReplayPoint } from "../../world/replay";
import { PlaybackBar } from "./PlaybackBar";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  cleanup();
  setReplayPoint("w_live", null);
});

const layout = villageBasicLayout() as unknown as Layout;
const run = () => {
  resetEvents();
  return [
    ev("world.started", "s", "w"),
    ev("agent.moved", "A_l1", "B1"),
    ev("agent.moved", "A_s1", "B2"),
    ev("world.completed", "A_dir", "w"),
  ];
};

const open = async (events = run()) => {
  const m = mount(withClient(fakeWorld(layout, events).client, <PlaybackBar worldId="w_live" />));
  await act(async () => {
    await Promise.resolve();
  });
  return m;
};

const press = (m: { container: HTMLElement }, name: string) =>
  click(
    [...m.container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes(name) || b.getAttribute("aria-label")?.includes(name),
    ) as Element,
  );

describe("TW-3 PlaybackBar replay controls and scrubber", () => {
  it("renders all replay control buttons: Play/Pause, 1×, 2×, Catch up, and Whole run", async () => {
    const m = await open();
    const buttons = [...m.container.querySelectorAll("button")].map((b) =>
      b.textContent?.trim(),
    );
    expect(buttons).toContain("Play / Pause");
    expect(buttons).toContain("1×");
    expect(buttons).toContain("2×");
    expect(buttons).toContain("Catch up");
    expect(buttons).toContain("Whole run");
  });

  it("renders scrubber with track, fill, and event metadata label", async () => {
    const m = await open();
    const scrubber = m.container.querySelector("[data-testid='playback-scrubber']");
    expect(scrubber).not.toBeNull();

    const track = scrubber?.querySelector(".tw-play__track");
    expect(track).not.toBeNull();

    const fill = scrubber?.querySelector(".tw-play__fill");
    expect(fill).not.toBeNull();

    const meta = scrubber?.querySelector(".tw-play__meta");
    expect(meta).not.toBeNull();
    // 4 events, completed run at the end: "event 4 of 4 · world.completed"
    expect(meta?.textContent).toBe("event 4 of 4 · world.completed");
  });

  it("toggles play/pause when Play / Pause button is clicked", async () => {
    const m = await open();
    const playPauseBtn = [...m.container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Play / Pause"),
    );
    expect(playPauseBtn?.getAttribute("aria-pressed")).toBe("true"); // initially paused

    // Click to start 1x
    press(m, "Play / Pause");
    expect(playPauseBtn?.getAttribute("aria-pressed")).toBe("false");

    // Click again to pause
    press(m, "Play / Pause");
    expect(playPauseBtn?.getAttribute("aria-pressed")).toBe("true");
  });

  it("sets speed to 2x or catch up when clicked", async () => {
    const m = await open();
    const btn2x = [...m.container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("2×"),
    );
    const btnCatch = [...m.container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Catch up"),
    );

    press(m, "2×");
    expect(btn2x?.getAttribute("aria-pressed")).toBe("true");

    press(m, "Catch up");
    expect(btnCatch?.getAttribute("aria-pressed")).toBe("true");
    expect(btn2x?.getAttribute("aria-pressed")).toBe("false");
  });

  it("handles Whole run button to jump to start or end", async () => {
    const m = await open();
    // Initially at whole run (point is null)
    expect(getReplayPoint("w_live")).toBeNull();

    // Clicking Whole run resets to start (point 0)
    press(m, "Whole run");
    expect(getReplayPoint("w_live")).toBe(0);

    // Clicking Whole run again restores to null (whole run)
    press(m, "Whole run");
    expect(getReplayPoint("w_live")).toBeNull();
  });
});
