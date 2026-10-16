// @vitest-environment happy-dom
// WORLD-LIVE (c): the Delivery Dock under the map says what is true (nothing delivered / result ready), and the
// Result panel opens by itself when the delivery is recorded while the page is open: the result's own title and
// summary, the output, Open / Copy / Download. A run already delivered at page open is not announced again.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click } from "../../../../test-support/park/componentsHarness";
import {
  control,
  hasControl,
  liveWorldsApi,
  mountWorld,
  settle,
  stubClipboard,
} from "../../../../test-support/park/worldHarness";
import { HttpClient } from "../../../api/http";
import { installResultReader } from "../../api/results";
import { resultHeadline } from "./ResultPanel";
import type { RunEvent } from "./useRunEvents";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

let seq = 0;
const ev = (type: string, summary: string, data: unknown = {}): RunEvent => ({
  seq: ++seq,
  type,
  ts: `2026-10-16T05:${String(seq).padStart(2, "0")}:00.000Z`,
  credits: 0,
  summary,
  data,
});
const head = (): RunEvent[] => {
  seq = 0;
  return [
    ev("world.requested", "You asked Tilo to plan the trip.", { title: "Plan a trip" }),
    ev("budget.granted", "You approved a budget of 40 credits.", { granted: 40, cap: 40 }),
    ev("world.planned", "Planned.", { tier: "village", approach: "quick", unit_count: 1 }),
    ev("world.started", "Started.", { budget_cap: 40 }),
  ];
};
const tail = (): RunEvent[] => [
  ev("artifact.delivered", "The item was delivered.", {
    artifact: { artifact_id: "art_plan", version: 1 },
    format: "in_app",
    outbox_id: null,
  }),
  ev("world.completed", "Done.", { credits_used: 2, deliverable_count: 1 }),
];
const TEXT =
  "# Lisbon in four days\n\nDay one is the old town, then the coast.\n\n- Day two: Sintra\n";

async function run(before: RunEvent[], after: RunEvent[]) {
  const api = liveWorldsApi();
  installResultReader(api, async () => new Blob([TEXT], { type: "text/markdown" }));
  const client = new HttpClient({
    baseUrl: "http://localhost:0",
    fetch: async () => new Response("{}", { status: 404 }),
  });
  let push: ((e: never) => void) | null = null;
  client.subscribeEvents = (_world, onEvent) => {
    push = onEvent as unknown as (e: never) => void;
    return () => undefined;
  };
  const rig = await mountWorld({ id: "hires", api, client });
  const send = async (events: RunEvent[]) => {
    await act(async () => {
      for (const e of events) push?.(e as never);
    });
    await settle();
  };
  await send(before);
  return { rig, send, after };
}

describe("WORLD-LIVE: the delivery spot and the Result panel", () => {
  it("WORLD_LIVE_the_dock_says_nothing_is_delivered_until_the_run_records_it", async () => {
    const { rig } = await run(head(), []);
    const dock = rig.el.querySelector('[data-testid="delivery-dock"]');
    expect(dock?.textContent).toContain("Delivery Dock");
    expect(dock?.textContent).toContain("Nothing delivered yet");
    expect(rig.el.querySelector('[role="dialog"][aria-label="Result"]')).toBeNull();
  });

  it("WORLD_LIVE_a_delivery_recorded_while_open_opens_the_result_with_title_summary_and_output", async () => {
    const { rig, send } = await run(head(), []);
    await send(tail());
    const dialog = rig.el.querySelector('[role="dialog"][aria-label="Result"]') as HTMLElement;
    expect(dialog).not.toBeNull();
    expect(dialog.textContent).toContain("Lisbon in four days");
    expect(dialog.textContent).toContain("Day one is the old town, then the coast.");
    expect(dialog.textContent).toContain("Day two: Sintra"); // the output itself, not only a summary
    for (const label of ["Open result", "Copy", "Download", "Close"])
      expect(hasControl(dialog, label)).toBe(true);
    expect(rig.el.querySelector('[data-testid="delivery-dock"]')?.textContent).toContain(
      "Result ready",
    );
  });

  it("WORLD_LIVE_copy_puts_the_output_on_the_clipboard_and_close_returns_to_the_page", async () => {
    const writeText = vi.fn(async () => undefined);
    const restore = stubClipboard(writeText);
    try {
      const { rig, send } = await run(head(), []);
      await send(tail());
      const dialog = rig.el.querySelector('[role="dialog"][aria-label="Result"]') as HTMLElement;
      click(control(dialog, "Copy"));
      await settle();
      expect(writeText).toHaveBeenCalledWith(TEXT);
      expect(dialog.textContent).toContain("Copied to the clipboard");
      click(control(dialog, "Close"));
      await settle();
      expect(rig.el.querySelector('[role="dialog"][aria-label="Result"]')).toBeNull();
    } finally {
      restore();
    }
  });

  it("WORLD_LIVE_a_run_already_delivered_at_page_open_is_offered_not_announced", async () => {
    // The whole recorded history arrives in one batch: the page never saw the run undelivered.
    const { rig } = await run([...head(), ...tail()], []);
    expect(rig.el.querySelector('[role="dialog"][aria-label="Result"]')).toBeNull();
    click(control(rig.el, "Read the result"));
    await settle();
    expect(rig.el.querySelector('[role="dialog"][aria-label="Result"]')?.textContent).toContain(
      "Lisbon in four days",
    );
  });

  it("WORLD_LIVE_the_headline_is_the_outputs_own_heading_and_first_prose_line", () => {
    expect(resultHeadline(TEXT, "Plan a trip")).toEqual({
      title: "Lisbon in four days",
      summary: "Day one is the old town, then the coast.",
    });
    expect(resultHeadline("just words here", "Plan a trip")).toEqual({
      title: "Plan a trip",
      summary: "just words here",
    });
    expect(resultHeadline("", "Plan a trip")).toEqual({ title: "Plan a trip", summary: "" });
    expect(resultHeadline(`# T\n\n${"x".repeat(400)}`, "w").summary.length).toBeLessThanOrEqual(
      220,
    );
  });
});
