// @vitest-environment happy-dom
// TW-1b acceptance: World responsive layout for 768–1279 px, two-row header,
// stage directly under header, rail drops below stage or narrows.
// Tested at 800, 1024, 1280 and 390 in light and dark modes.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { liveWorldsApi, mountWorld, textOf } from "../../../../test-support/park/worldHarness";
import { HttpClient } from "../../../api/http";
import type { RunEvent } from "./useRunEvents";

vi.mock("../../../worldView/LiveStageEmbed", () => ({
  default: () => <div data-testid="live-stage-stub" />,
  LiveChat: () => <div data-testid="live-chat-stub">Live chat</div>,
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

let seq = 0;
const ev = (
  type: string,
  summary: string,
  data: unknown = {},
  extra: Partial<RunEvent> = {},
): RunEvent => ({
  seq: ++seq,
  type,
  ts: `2026-10-15T09:${String(seq).padStart(2, "0")}:00.000Z`,
  credits: 0,
  summary,
  data,
  ...extra,
});

const RUN = (): RunEvent[] => {
  seq = 0;
  return [
    ev("world.requested", "You asked Tilo to plan the work.", { title: "Road trip" }),
    ev("world.started", "Run started.", {}),
    ev("world.planned", "Director planned 3 units.", { tier: "town" }),
    ev("building.planned", "Unit U1 planned.", { unit: "U1" }),
    ev("agent.spawned", "Agent Wren arrived.", { agent: "Wren" }),
    ev(
      "agent.working",
      "Wren is searching options.",
      { agent: "Wren", tool: "Web" },
      { credits: 4 },
    ),
    ev("building.completed", "Unit U1 done.", { unit: "U1" }),
  ];
};

function liveFeed() {
  const client = new HttpClient({
    baseUrl: "http://localhost:0",
    fetch: async () => new Response("{}", { status: 404 }),
  });
  let push: ((e: never) => void) | null = null;
  client.subscribeEvents = (_world, onEvent) => {
    push = onEvent as unknown as (e: never) => void;
    return () => undefined;
  };
  const emit = async (...events: RunEvent[]) => {
    await act(async () => {
      for (const e of events) push?.(e as never);
    });
  };
  return { client, emit };
}

describe("TW_1b: CSS Media Queries and Responsive Rules in World.studio.css", () => {
  const css = readFileSync(join(__dirname, "World.studio.css"), "utf8");

  it("TW_1b_css_contains_tablet_two_row_header_media_query_761_to_1279", () => {
    expect(css).toMatch(/@media\s*\(min-width:\s*761px\)\s*and\s*\(max-width:\s*1279px\)/);
    // Header is grid with two rows and display: contents on titles
    expect(css).toMatch(/\[data-park\]\s+\.park-world-titles\s*\{\s*display:\s*contents;/);
    // Titleline on row 1
    expect(css).toMatch(/\[data-park\]\s+\.park-world-titleline\s*\{\s*grid-row:\s*1;/);
    // Metalist on row 2
    expect(css).toMatch(/\[data-park\]\s+\.park-world-metalist\s*\{\s*grid-row:\s*2;/);
    // Stepbar on row 2
    expect(css).toMatch(/\[data-park\]\s+\.park-world-headstepbar\s*\{\s*grid-row:\s*2;/);
    // Creditsbar on row 2
    expect(css).toMatch(/\[data-park\]\s+\.park-world-headcreditsbar\s*\{\s*grid-row:\s*2;/);
    // Actions on row 2
    expect(css).toMatch(/\[data-park\]\s+\.park-world-actions\s*\{\s*grid-row:\s*2;/);
  });

  it("TW_1b_css_removes_large_empty_gap_above_header_at_tablet", () => {
    expect(css).toMatch(/\[data-park\]\s+\.park-world-root\s*\{\s*margin-top:\s*-16px;/);
    expect(css).toMatch(
      /\[data-park\]\s+\.park-world-root\s*>\s*\.park-sheet\s*\{\s*padding-top:\s*0;\s*gap:\s*12px;/,
    );
  });

  it("TW_1b_css_hides_non_failed_runstatus_so_stage_starts_directly_under_header", () => {
    expect(css).toMatch(
      /\[data-park\]\s+\.park-world-runstatus:not\(\[data-phase="failed"\]\)\s*\{\s*display:\s*none;\s*\}/,
    );
  });

  it("TW_1b_css_rail_drops_below_stage_at_768_to_1059_and_narrows_at_1060_to_1279", () => {
    // 768-1059 drops below stage
    expect(css).toMatch(/@media\s*\(min-width:\s*761px\)\s*and\s*\(max-width:\s*1059px\)/);
    expect(css).toMatch(
      /\[data-park\]\s+\.park-world-top\s*\{\s*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*!important;/,
    );
    // 1060-1279 narrows
    expect(css).toMatch(/@media\s*\(min-width:\s*1060px\)\s*and\s*\(max-width:\s*1279px\)/);
    expect(css).toMatch(/\[data-park\]\s+\.park-world-panels\s*\{[^}]*max-width:\s*420px;/);
    // 1280+ desktop rail 500px
    expect(css).toMatch(/@media\s*\(min-width:\s*1280px\)/);
    expect(css).toMatch(/\[data-park\]\s+\.park-world-panels\s*\{[^}]*max-width:\s*500px;/);
  });
});

describe("TW_1b: Viewport 800 (Tablet Narrow) in light and dark", () => {
  for (const night of [false, true]) {
    const themeName = night ? "dark" : "light";

    it(`TW_1b_viewport_800_${themeName}_renders_two_calm_rows_and_single_column_top`, async () => {
      const { client, emit } = liveFeed();
      const { el } = await mountWorld({
        id: "hires",
        api: liveWorldsApi(),
        client,
        app: { vw: 800, night, time: night ? "night" : "day" },
      });
      await emit(...RUN());

      const head = el.querySelector(".park-world-head");
      expect(head).not.toBeNull();

      // Row 1 elements
      const back = head?.querySelector(".park-world-back");
      expect(back).not.toBeNull();
      const titleline = head?.querySelector(".park-world-titleline");
      expect(titleline).not.toBeNull();
      const h1 = titleline?.querySelector("h1.park-world-h1");
      expect(h1).not.toBeNull();
      const sizeChip = titleline?.querySelector(".park-world-sizechip");
      expect(sizeChip).not.toBeNull();
      const statusChip = titleline?.querySelector(".park-world-chip");
      expect(statusChip).not.toBeNull();

      // Row 2 elements
      const metalist = head?.querySelector(".park-world-metalist");
      expect(metalist).not.toBeNull();
      const meta = metalist?.querySelector(".park-world-meta");
      expect(meta).not.toBeNull();
      expect(textOf(meta as Element)).toContain("agent");

      const stepBar = head?.querySelector(".park-world-headstepbar");
      expect(stepBar).not.toBeNull();
      expect(textOf(stepBar as Element)).toContain("steps done");

      const creditsBar = head?.querySelector(".park-world-headcreditsbar");
      expect(creditsBar).not.toBeNull();
      expect(textOf(creditsBar as Element)).toContain("credits");

      const actions = head?.querySelector(".park-world-actions");
      expect(actions).not.toBeNull();
      expect(actions?.querySelector("button")).not.toBeNull();

      // Top grid layout: rail drops below stage at 800px (wide is false)
      const top = el.querySelector(".park-world-top") as HTMLElement;
      expect(top).not.toBeNull();
      expect(top.style.gridTemplateColumns).toBe("minmax(0,1fr)");

      // Stage card exists and starts directly under header
      const mapcard = top.querySelector(".park-world-mapcard");
      expect(mapcard).not.toBeNull();

      // Panels exist
      const panels = top.querySelector(".park-world-panels");
      expect(panels).not.toBeNull();
    });
  }
});

describe("TW_1b: Viewport 1024 (Tablet Wide) in light and dark", () => {
  for (const night of [false, true]) {
    const themeName = night ? "dark" : "light";

    it(`TW_1b_viewport_1024_${themeName}_renders_two_calm_rows_and_single_column_top`, async () => {
      const { client, emit } = liveFeed();
      const { el } = await mountWorld({
        id: "hires",
        api: liveWorldsApi(),
        client,
        app: { vw: 1024, night, time: night ? "night" : "day" },
      });
      await emit(...RUN());

      const head = el.querySelector(".park-world-head");
      expect(head).not.toBeNull();

      // Row 1 elements
      expect(head?.querySelector(".park-world-back")).not.toBeNull();
      expect(head?.querySelector(".park-world-titleline h1.park-world-h1")).not.toBeNull();
      expect(head?.querySelector(".park-world-titleline .park-world-sizechip")).not.toBeNull();
      expect(head?.querySelector(".park-world-titleline .park-world-chip")).not.toBeNull();

      // Row 2 elements
      expect(head?.querySelector(".park-world-metalist .park-world-meta")).not.toBeNull();
      expect(head?.querySelector(".park-world-headstepbar")).not.toBeNull();
      expect(head?.querySelector(".park-world-headcreditsbar")).not.toBeNull();
      expect(head?.querySelector(".park-world-actions")).not.toBeNull();

      // Top grid layout: at 1024 ( < 1060 ), rail drops below stage
      const top = el.querySelector(".park-world-top") as HTMLElement;
      expect(top).not.toBeNull();
      expect(top.style.gridTemplateColumns).toBe("minmax(0,1fr)");
    });
  }
});

describe("TW_1b: Viewport 1280 (Desktop Compact) in light and dark", () => {
  for (const night of [false, true]) {
    const themeName = night ? "dark" : "light";

    it(`TW_1b_viewport_1280_${themeName}_renders_side_by_side_layout`, async () => {
      const { client, emit } = liveFeed();
      const { el } = await mountWorld({
        id: "hires",
        api: liveWorldsApi(),
        client,
        app: { vw: 1280, night, time: night ? "night" : "day" },
      });
      await emit(...RUN());

      const head = el.querySelector(".park-world-head");
      expect(head).not.toBeNull();

      // Header elements all present
      expect(head?.querySelector(".park-world-back")).not.toBeNull();
      expect(head?.querySelector("h1.park-world-h1")).not.toBeNull();
      expect(head?.querySelector(".park-world-sizechip")).not.toBeNull();
      expect(head?.querySelector(".park-world-chip")).not.toBeNull();
      expect(head?.querySelector(".park-world-meta")).not.toBeNull();
      expect(head?.querySelector(".park-world-headstepbar")).not.toBeNull();
      expect(head?.querySelector(".park-world-headcreditsbar")).not.toBeNull();
      expect(head?.querySelector(".park-world-actions")).not.toBeNull();

      // Top grid layout: wide is true (>= 1060), side by side
      const top = el.querySelector(".park-world-top") as HTMLElement;
      expect(top).not.toBeNull();
      expect(top.style.gridTemplateColumns).toBe("minmax(0,3fr) minmax(0,2fr)");
    });
  }
});

describe("TW_1b: Viewport 390 (Mobile Phone) in light and dark", () => {
  for (const night of [false, true]) {
    const themeName = night ? "dark" : "light";

    it(`TW_1b_viewport_390_${themeName}_renders_compact_header_and_panels`, async () => {
      const { client, emit } = liveFeed();
      const { el } = await mountWorld({
        id: "hires",
        api: liveWorldsApi(),
        client,
        app: { vw: 390, night, time: night ? "night" : "day" },
      });
      await emit(...RUN());

      const head = el.querySelector(".park-world-head");
      expect(head).not.toBeNull();

      // Back link and Title exist
      expect(head?.querySelector(".park-world-back")).not.toBeNull();
      expect(head?.querySelector("h1.park-world-h1")).not.toBeNull();
      expect(head?.querySelector(".park-world-sizechip")).not.toBeNull();

      // Rail panels exist and carry sheet handle
      const panels = el.querySelector(".park-world-panels");
      expect(panels).not.toBeNull();
      expect(panels?.querySelector(".park-world-sheethandle")).not.toBeNull();

      // Single column layout at 390
      const top = el.querySelector(".park-world-top") as HTMLElement;
      expect(top).not.toBeNull();
      expect(top.style.gridTemplateColumns).toBe("minmax(0,1fr)");
    });
  }
});
