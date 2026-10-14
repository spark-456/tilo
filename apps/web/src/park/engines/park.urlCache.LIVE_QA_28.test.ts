// LIVE-QA row 28: a picture the engine has drawn gets one blob URL for the session. Drawing the same agent or building
// again (a route change, a revisit) hands back the URL it already has, so the browser reuses the loaded image and
// no new object URL is made. Another picture, or the same one by night, is its own URL.
import { describe, expect, it } from "vitest";
import { FakeBlob } from "../../../test-support/park/engineProto";
import { createPark } from "./park";
import type { H } from "./types";
import { createWorld } from "./world";

const h: H = (tag, props, ...children) => ({ tag, props, children }) as never;

function engine() {
  const made: string[] = [];
  const env = {
    Blob: FakeBlob as unknown as typeof Blob,
    createObjectURL: (b: Blob) => {
      made.push((b as unknown as FakeBlob).text);
      return `blob:u${made.length}`;
    },
  };
  return { made, park: createPark(h, createWorld as never, env as never) };
}
const src = (el: unknown): string => (el as { props: { src: string } }).props.src;

describe("LIVE_QA_28_url_cache", () => {
  it("LIVE_QA_28_the_same_agent_drawn_again_reuses_its_url_and_makes_nothing", () => {
    const { made, park } = engine();
    const first = src(park.agent({ role: "builder", expr: "needs" }, 30, false));
    const again = src(park.agent({ role: "builder", expr: "needs" }, 30, false));
    expect(again).toBe(first);
    expect(made).toHaveLength(1);
  });

  it("LIVE_QA_28_another_picture_or_the_night_one_is_its_own_url", () => {
    const { made, park } = engine();
    const day = src(park.agent({ role: "builder", expr: "needs" }, 30, false));
    const night = src(park.agent({ role: "builder", expr: "needs" }, 30, true));
    const other = src(park.agent({ role: "builder", expr: "walking" }, 30, false));
    expect(new Set([day, night, other]).size).toBe(3);
    expect(made).toHaveLength(3);
  });
});
