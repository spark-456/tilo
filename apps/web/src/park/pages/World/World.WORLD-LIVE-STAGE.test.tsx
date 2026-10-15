// @vitest-environment happy-dom
// WORLD-LIVE (b): a real run on the World page is drawn by the live stage when the browser has WebGL2, and keeps
// the recorded text map when it has not (the Story and the static picture take over, never a blank card).
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { liveWorldsApi, mountWorld, settle } from "../../../../test-support/park/worldHarness";
import { HttpClient } from "../../../api/http";
import type { RunEvent } from "./useRunEvents";

vi.mock("../../../worldView/LiveStageEmbed", () => ({
  default: ({ worldId }: { worldId: string }) => <div data-testid="live-stage-stub">{worldId}</div>,
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const events: RunEvent[] = [
  {
    seq: 1,
    type: "world.started",
    ts: "2026-10-16T05:01:00.000Z",
    credits: 0,
    summary: "Started.",
    data: {},
  },
  {
    seq: 2,
    type: "district.created",
    ts: "2026-10-16T05:02:00.000Z",
    credits: 0,
    summary: "District set up.",
    data: { name: "Workstream 1", lead: "A_lead1" },
    target: "D1",
  } as RunEvent,
];

async function open(webgl: boolean) {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(((kind: string) =>
    webgl && kind === "webgl2" ? ({} as unknown) : null) as never);
  const client = new HttpClient({
    baseUrl: "http://localhost:0",
    fetch: async () => new Response("{}", { status: 404 }),
  });
  let push: ((e: never) => void) | null = null;
  client.subscribeEvents = (_world, onEvent) => {
    push = onEvent as unknown as (e: never) => void;
    return () => undefined;
  };
  const rig = await mountWorld({ id: "hires", api: liveWorldsApi(), client });
  await act(async () => {
    for (const e of events) push?.(e as never);
  });
  await settle();
  return rig;
}

describe("WORLD-LIVE: the live stage on the World page", () => {
  it("WORLD_LIVE_stage_with_webgl2_the_live_stage_replaces_the_text_map", async () => {
    const rig = await open(true);
    expect(rig.el.querySelector('[data-testid="live-stage-stub"]')?.textContent).toBe("hires");
    expect(rig.el.querySelector("[data-recorded-world]")).toBeNull();
    expect(rig.el.querySelector(".park-world-map--live")).not.toBeNull();
  });

  it("WORLD_LIVE_stage_without_webgl2_keeps_the_recorded_map", async () => {
    const rig = await open(false);
    expect(rig.el.querySelector('[data-testid="live-stage-stub"]')).toBeNull();
    expect(rig.el.querySelector("[data-recorded-world]")).not.toBeNull();
  });
});
