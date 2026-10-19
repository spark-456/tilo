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
const delivered = (id: string, label: string) =>
  ev("artifact.delivered", `${label} is ready.`, {
    artifact: { artifact_id: id, version: 1, label },
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
  const read = vi.fn(
    async (_world: string, artifact?: string) =>
      new Blob([artifact === "art_note" ? "# Trip notes\n" : "# Trip plan\n"], {
        type: "text/markdown",
      }),
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
      ...ids.map((id, index) => delivered(id, index === 0 ? "Trip plan" : "Trip notes")),
      ev("world.completed", "Done.", { credits_used: 2, deliverable_count: ids.length }),
    ])
      push?.(e as never);
  });
  await settle();
  return { rig, read };
}

describe("RESULT_LIVE: every delivered item can be opened", () => {
  it("test_RESULT_TAB_main_named_deliverable_precedes_collapsed_named_working_files", async () => {
    const { rig, read } = await finishedRun(["art_plan", "art_note"]);
    expect(read).toHaveBeenCalledWith("hires", "art_plan");
    expect(rig.el.querySelector('[data-testid="run-result"]')?.textContent).toContain("Trip plan");
    expect(rig.el.querySelector('[data-testid="result-text"]')?.textContent).toContain("Trip plan");
    const files = rig.el.querySelector<HTMLDetailsElement>("details[data-testid='working-files']");
    expect(files?.open).toBe(false);
    expect(files?.textContent).toContain("Trip notes");
    expect(files?.textContent).not.toMatch(/Item\s*[1-9]/);
    expect(rig.el.querySelector('[data-testid="run-result"]')?.textContent).not.toMatch(
      /art_(?:plan|note)/,
    );
    expect(hasControl(rig.el, "Open result")).toBe(true);
    if (files) files.open = true;
    const clicks: HTMLAnchorElement[] = [];
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:item");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicks.push(this);
    });

    click(control(rig.el, "Download working file: Trip notes"));
    await settle();
    expect(read).toHaveBeenLastCalledWith("hires", "art_note");
    expect(clicks.at(-1)?.download).toBe("tilo-result-Trip notes.md");

    click(control(rig.el, "Open working file: Trip notes"));
    await settle();
    expect(read).toHaveBeenLastCalledWith("hires", "art_note");
  });

  it("RESULT_LIVE_a_single_delivery_shows_no_item_list", async () => {
    const { rig } = await finishedRun(["art_plan"]);
    expect(rig.el.querySelector("details[data-testid='working-files']")).toBeNull();
    expect(hasControl(rig.el, "Download")).toBe(true);
  });
});
