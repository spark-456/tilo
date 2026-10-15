// @vitest-environment happy-dom
// RESULT-LIVE: a run that delivered two items shows the main one (GET /result) and lists every delivered item with
// Open and Download, each read from GET /result?artifact=<id> only when asked for.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click } from "../../../../test-support/park/componentsHarness";
import {
  control,
  hasControl,
  liveWorldsApi,
  mountWorld,
  settle,
} from "../../../../test-support/park/worldHarness";
import { HttpClient } from "../../../api/http";
import { installResultReader } from "../../api/results";
import type { RunEvent } from "./useRunEvents";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

let seq = 0;
const ev = (type: string, summary: string, data: unknown = {}): RunEvent => ({
  seq: ++seq,
  type,
  ts: `2026-10-15T05:${String(seq).padStart(2, "0")}:00.000Z`,
  credits: 0,
  summary,
  data,
});
const delivered = (id: string) =>
  ev("artifact.delivered", "The item was delivered.", {
    artifact: { artifact_id: id, version: 1 },
    format: "in_app",
    outbox_id: null,
  });

async function finishedRun(ids: string[]) {
  seq = 0;
  const client = new HttpClient({
    baseUrl: "http://localhost:0",
    fetch: async () => new Response("{}", { status: 404 }),
  });
  let push: ((e: never) => void) | null = null;
  client.subscribeEvents = (_world, onEvent) => {
    push = onEvent as unknown as (e: never) => void;
    return () => undefined;
  };
  const read = vi.fn(async (_world: string, artifact?: string) =>
    artifact === "art_note"
      ? Promise.reject(new Error("404"))
      : new Blob([artifact ? `# ${artifact}\n` : "# Trip plan\n"], { type: "text/markdown" }),
  );
  const api = liveWorldsApi();
  installResultReader(api, read);
  const rig = await mountWorld({ id: "hires", api, client });
  await act(async () => {
    for (const e of [
      ev("world.requested", "You asked Tilo to plan the trip.", { title: "Plan a trip" }),
      ev("budget.granted", "You approved a budget of 40 credits.", { granted: 40, cap: 40 }),
      ev("world.planned", "Planned.", {
        tier: "village",
        approach: "quick",
        unit_count: 2,
        credits: { min: 5, max: 20 },
      }),
      ev("world.started", "Started.", { budget_cap: 40 }),
      ...ids.map(delivered),
      ev("world.completed", "Done.", { credits_used: 2, deliverable_count: ids.length }),
    ])
      push?.(e as never);
  });
  await settle();
  return { rig, read };
}

describe("RESULT_LIVE: every delivered item can be opened", () => {
  it("RESULT_LIVE_shows_the_main_item_and_reads_each_listed_item_by_its_id", async () => {
    const { rig, read } = await finishedRun(["art_plan", "art_note"]);
    expect(read).toHaveBeenCalledWith("hires", undefined);
    expect(rig.el.querySelector('[data-testid="result-text"]')?.textContent).toContain("Trip plan");
    expect(hasControl(rig.el, "Open item 2")).toBe(true);
    const clicks: HTMLAnchorElement[] = [];
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:item");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicks.push(this);
    });

    click(control(rig.el, "Download item 1"));
    await settle();
    expect(read).toHaveBeenLastCalledWith("hires", "art_plan");
    expect(clicks.at(-1)?.download).toBe("tilo-result-hires-1.md");

    click(control(rig.el, "Open item 2"));
    await settle();
    expect(read).toHaveBeenLastCalledWith("hires", "art_note");
    expect(
      rig.el.querySelector('[data-testid="delivered-items"] [role="alert"]')?.textContent,
    ).toContain("could not be loaded");
  });

  it("RESULT_LIVE_a_single_delivery_shows_no_item_list", async () => {
    const { rig } = await finishedRun(["art_plan"]);
    expect(rig.el.querySelector('[data-testid="delivered-items"]')).toBeNull();
    expect(hasControl(rig.el, "Download")).toBe(true);
  });
});
