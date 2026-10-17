// @vitest-environment happy-dom
// TW-1 acceptance: World layout, 60px desktop header, right rail 500px, Story Plain|Trace toggle,
// More drawer in rail, phone 390 bottom sheet (372 peek / 600 tall), 44px targets.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click } from "../../../../test-support/park/componentsHarness";
import {
  control,
  liveWorldsApi,
  mountWorld,
  settle,
  textOf,
} from "../../../../test-support/park/worldHarness";
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

describe("TW_1: Desktop 60px header", () => {
  it("TW_1_desktop_header_renders_title_sizechip_statuschip_meta_bars_pause_and_more", async () => {
    const { client, emit } = liveFeed();
    const { el } = await mountWorld({ id: "hires", api: liveWorldsApi(), client });
    await emit(...RUN());
    const head = el.querySelector(".park-world-head");
    expect(head).not.toBeNull();

    // 1. Back link
    const back = head?.querySelector(".park-world-back");
    expect(back).not.toBeNull();

    // 2. Title
    const h1 = head?.querySelector("h1.park-world-h1");
    expect(h1).not.toBeNull();
    expect(textOf(h1 as Element)).toBeTruthy();

    // 3. Size chip
    const sizeChip = head?.querySelector(".park-world-sizechip");
    expect(sizeChip).not.toBeNull();
    expect(["Village", "Town", "City"]).toContain(textOf(sizeChip as Element).trim());

    // 4. Status chip
    const statusChip = head?.querySelector(".park-world-chip");
    expect(statusChip).not.toBeNull();

    // 5. Meta line ("Started ... · ... agents")
    const meta = head?.querySelector(".park-world-meta");
    expect(meta).not.toBeNull();
    expect(textOf(meta as Element)).toMatch(/started|Recorded/i);

    // 6. Steps done bar
    const stepBar = head?.querySelector(".park-world-headstepbar");
    expect(stepBar).not.toBeNull();
    expect(textOf(stepBar as Element)).toContain("steps done");

    // 7. Credits bar
    const creditsBar = head?.querySelector(".park-world-headcreditsbar");
    expect(creditsBar).not.toBeNull();
    expect(textOf(creditsBar as Element)).toContain("credits");

    // 8. Pause run button
    const pauseBtn = head?.querySelector(
      'button[aria-label="Pause run"], button[aria-label="Resume run"]',
    );
    expect(pauseBtn).not.toBeNull();

    // 9. More button
    const moreBtn = head?.querySelector('button[aria-label="More"]');
    expect(moreBtn).not.toBeNull();
  });
});

describe("TW_1: Right rail and tabs", () => {
  it("TW_1_right_rail_has_tabs_and_Story_toggle_between_plain_and_trace", async () => {
    const { client, emit } = liveFeed();
    const { el } = await mountWorld({ id: "hires", api: liveWorldsApi(), client });
    await emit(...RUN());
    const panels = el.querySelector(".park-world-panels");
    expect(panels).not.toBeNull();

    // Tabs
    const tabs = el.querySelectorAll('[role="tab"]');
    const tabNames = [...tabs].map((t) => t.textContent?.replace(/[0-9/]/g, "").trim());
    expect(tabNames).toContain("Story");
    expect(tabNames).toContain("Chat");
    expect(tabNames).toContain("Result");
    expect(tabNames).toContain("Steps");

    // Plain | Trace toggle
    const plainBtn = el.querySelector('.park-world-storyviewbtn[role="radio"]:first-child');
    const traceBtn = el.querySelector('.park-world-storyviewbtn[role="radio"]:last-child');
    expect(plainBtn).not.toBeNull();
    expect(traceBtn).not.toBeNull();
    expect(textOf(plainBtn as Element)).toBe("Plain");
    expect(textOf(traceBtn as Element)).toBe("Trace");
    expect(plainBtn?.getAttribute("aria-checked")).toBe("true");

    // Default view is plain story
    expect(el.querySelector("ol.park-world-story")).not.toBeNull();
    expect(el.querySelector(".park-world-trace")).toBeNull();

    // Switch to Trace
    act(() => {
      click(traceBtn as HTMLElement);
    });

    expect(traceBtn?.getAttribute("aria-checked")).toBe("true");
    expect(el.querySelector(".park-world-trace")).not.toBeNull();
    expect(textOf(el.querySelector(".park-world-tracehead") as Element)).toContain("TIME");
    expect(textOf(el.querySelector(".park-world-tracehead") as Element)).toContain("CR");
    expect(textOf(el.querySelector(".park-world-tracetotal") as Element)).toContain("Total so far");
  });
});

describe("TW_1: More panel in rail area", () => {
  it("TW_1_more_opens_into_rail_area_and_closes_with_close_button", async () => {
    const { client, emit } = liveFeed();
    const { el } = await mountWorld({ id: "hires", api: liveWorldsApi(), client });
    await emit(...RUN());
    const moreBtn = el.querySelector(
      '.park-world-actions button[aria-label="More"]',
    ) as HTMLElement;
    expect(moreBtn).not.toBeNull();

    const moreDetails = el.querySelector("details.park-world-more") as HTMLDetailsElement;
    expect(moreDetails).not.toBeNull();
    expect(moreDetails.classList.contains("park-world-more--hidden")).toBe(true);

    // Click More
    act(() => {
      click(moreBtn);
    });

    expect(moreDetails.classList.contains("park-world-more--open")).toBe(true);
    expect(moreDetails.open).toBe(true);
    const closeBtn = el.querySelector("button.park-world-moreclose") as HTMLElement;
    expect(closeBtn).not.toBeNull();

    // Work items and proposals exist inside more
    expect(moreDetails.querySelector('[aria-label="Skill proposals"]')).not.toBeNull();
    expect(moreDetails.querySelector('[aria-label="Team work items"]')).not.toBeNull();

    // Click Close
    act(() => {
      click(closeBtn);
    });

    expect(moreDetails.classList.contains("park-world-more--hidden")).toBe(true);
  });
});

describe("TW_1: Phone bottom sheet", () => {
  it("TW_1_phone_bottom_sheet_sets_data_tall_for_peek_vs_tall_views", async () => {
    const { client, emit } = liveFeed();
    const { el } = await mountWorld({
      id: "hires",
      app: { vw: 390 },
      api: liveWorldsApi(),
      client,
    });
    await emit(...RUN());
    const panels = el.querySelector(".park-world-panels") as HTMLElement;
    expect(panels).not.toBeNull();

    // Handle exists
    expect(el.querySelector(".park-world-sheethandle")).not.toBeNull();

    // On story tab: peek (data-tall is false)
    expect(panels.getAttribute("data-tall")).toBe("false");

    // Switch to Chat tab: tall (data-tall is true)
    const chatTab = [...el.querySelectorAll('[role="tab"]')].find((t) =>
      t.textContent?.includes("Chat"),
    ) as HTMLElement;
    if (chatTab) {
      act(() => {
        click(chatTab);
      });
      await settle();
      expect(panels.getAttribute("data-tall")).toBe("true");
    }

    // Switch to Result tab: tall (data-tall is true)
    const resultTab = [...el.querySelectorAll('[role="tab"]')].find((t) =>
      t.textContent?.includes("Result"),
    ) as HTMLElement;
    act(() => {
      click(resultTab);
    });
    expect(panels.getAttribute("data-tall")).toBe("true");

    // Switch to Steps tab: peek (data-tall is false)
    const stepsTab = [...el.querySelectorAll('[role="tab"]')].find((t) =>
      t.textContent?.includes("Steps"),
    ) as HTMLElement;
    act(() => {
      click(stepsTab);
    });
    expect(panels.getAttribute("data-tall")).toBe("false");
  });
});
