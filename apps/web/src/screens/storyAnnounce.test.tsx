// @vitest-environment happy-dom
import type { Event } from "@tilo/contracts";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ANNOUNCE_DEBOUNCE_MS, announcement, useStoryAnnouncement } from "./storyAnnounce";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const row = (seq: number): Event => ({ seq, summary: `Row ${seq}` }) as Event;
const rows = (n: number): Event[] => Array.from({ length: n }, (_, i) => row(i + 1));

function Probe({ story, enabled }: { story: Event[]; enabled: boolean }) {
  return <p data-testid="said">{useStoryAnnouncement(story, enabled)}</p>;
}

describe("FR-WLD-11 Story announcements are batched, not per event", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const setup = async (story: Event[], enabled: boolean) => {
    const container = document.createElement("div");
    const root = createRoot(container);
    const render = (s: Event[], e = enabled) =>
      act(async () => {
        root.render(<Probe story={s} enabled={e} />);
      });
    await render(story);
    const said = () => container.textContent;
    const wait = (ms: number) =>
      act(async () => {
        vi.advanceTimersByTime(ms);
      });
    return { render, said, wait };
  };

  it("says nothing about the rows that were already there", async () => {
    const { said, wait } = await setup(rows(5), true);
    await wait(ANNOUNCE_DEBOUNCE_MS * 2);
    expect(said()).toBe("");
  });

  it("announces many new rows once, as a count and the latest summary", async () => {
    const { render, said, wait } = await setup(rows(2), true);
    for (let n = 3; n <= 8; n++) {
      await render(rows(n));
      await wait(ANNOUNCE_DEBOUNCE_MS / 4);
    }
    expect(said()).toBe("");
    await wait(ANNOUNCE_DEBOUNCE_MS);
    expect(said()).toBe(announcement(6, "Row 8"));
  });

  it("uses the singular for one new row", () => {
    expect(announcement(1, "Row 3")).toBe("1 new event. Latest: Row 3");
  });

  it("says nothing on a replay, however many rows are added", async () => {
    const { render, said, wait } = await setup(rows(2), false);
    await render(rows(40));
    await wait(ANNOUNCE_DEBOUNCE_MS * 2);
    expect(said()).toBe("");
  });

  it("says nothing when rows disappear (a scrub back)", async () => {
    const { render, said, wait } = await setup(rows(10), true);
    await render(rows(4));
    await wait(ANNOUNCE_DEBOUNCE_MS * 2);
    expect(said()).toBe("");
  });
});
