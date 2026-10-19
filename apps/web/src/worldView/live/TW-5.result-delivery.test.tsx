import type { Layout } from "@tilo/contracts";
// @vitest-environment happy-dom
/**
 * TW-5: Result tab with rich previews, delivery parcel moment, world.completed gather + hop + confetti,
 * and failure card on top of Story (design/tilo-w PROMPT.md, WORLD-W-TICKETS.md).
 */
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { villageBasicLayout } from "../../../test-support/worldFixtures";
import { ev, fakeWorld, resetEvents, withClient } from "../../../test-support/worldLive";
import { frameOf } from "../../world/frame";
import { applyEvent, createInitialState, standingAt } from "../../world/reducer";
import { registerProbe, resetSpotlights } from "../../world/spotlight";
import { AgentLayer } from "./AgentLayer";
import { FailureCard } from "./FailureCard";
import { ResultTab } from "./ResultTab";

afterEach(() => {
  cleanup();
  resetSpotlights();
  vi.restoreAllMocks();
});

const layout = structuredClone(villageBasicLayout()) as unknown as Layout;
for (const b of layout.semantic.levels[0]?.districts[0]?.buildings ?? []) {
  if (b.id === "B3") (b as { common_type?: string; name?: string }).common_type = "meeting_hall";
  if (b.id === "B4") (b as { common_type?: string; name?: string }).common_type = "delivery_dock";
}

const settle = () =>
  act(async () => {
    for (let i = 0; i < 4; i++) await Promise.resolve();
  });

describe("TW-5: Result tab and previews", () => {
  it("renders the recorded main deliverable and named working files", async () => {
    const events = [
      ev("world.started", "system", "w_live"),
      ev("artifact.delivered", "A_w1", "art_plan", {
        artifact: { artifact_id: "art_plan", label: "Porto offsite plan" },
        format: "pdf",
      }),
      ev("artifact.delivered", "A_l1", "art_budget", {
        artifact: { artifact_id: "art_budget", label: "Offsite budget.xlsx" },
        format: "xlsx",
      }),
    ];

    const onOpen = vi.fn();
    const onDownload = vi.fn();
    const onShare = vi.fn();

    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_live"
          events={events}
          onOpen={onOpen}
          onDownload={onDownload}
          onShare={onShare}
        />
      </div>,
    );
    await settle();

    // Main card
    const mainCard = m.container.querySelector('[data-testid="run-result"]');
    expect(mainCard).not.toBeNull();
    expect(mainCard?.textContent).toContain("Porto offsite plan");
    expect(mainCard?.textContent).toContain("PDF");
    expect(mainCard?.textContent).toContain("Open result");
    expect(mainCard?.textContent).toContain("Download");
    expect(mainCard?.textContent).toContain("Share");

    // Click Open, Download, Share
    const openBtn = m.container.querySelector<HTMLButtonElement>(".tw-res-btn--pri");
    openBtn?.click();
    expect(onOpen).toHaveBeenCalled();

    const downloadBtn = m.container.querySelectorAll<HTMLButtonElement>(".tw-res-btn--sec")[0];
    downloadBtn?.click();
    expect(onDownload).toHaveBeenCalled();

    const shareBtn = [...m.container.querySelectorAll<HTMLButtonElement>(".tw-res-btn--sec")].find(
      (button) => button.textContent?.trim() === "Share",
    );
    act(() => shareBtn?.click());
    expect(onShare).toHaveBeenCalled();

    // R-RESULT deliberately replaces the sample preview cards with only recorded deliverables.
    expect(m.container.textContent).not.toContain("ALSO DELIVERED");
    expect(m.container.textContent).toContain("Offsite budget.xlsx");
    expect(m.container.textContent).not.toContain("Kickoff deck");

    // Folded Working Files
    const files = m.container.querySelector<HTMLDetailsElement>(
      'details[data-testid="working-files"]',
    );
    expect(files).not.toBeNull();
    expect(files?.open).toBe(false);
    expect(files?.textContent).toContain("Offsite budget.xlsx");

    expect(m.container.textContent).not.toContain("artifact.delivered");
  });

  it("does not render working files when only a single deliverable was produced", async () => {
    const singleEvent = [
      ev("world.started", "system", "w_live"),
      ev("artifact.delivered", "A_w1", "art_plan", {
        artifact: { artifact_id: "art_plan", label: "Solo Document" },
      }),
    ];

    const m = mount(
      <div data-park="">
        <ResultTab worldId="w_live" events={singleEvent} />
      </div>,
    );
    await settle();

    expect(m.container.querySelector('details[data-testid="working-files"]')).toBeNull();
  });
});

describe("TW-5: Delivery moment and world.completed celebration", () => {
  it("arcs parcel from Meeting Hall to Delivery Dock on artifact.delivered", async () => {
    resetEvents();
    const world = fakeWorld(layout, [ev("world.started", "system", "w_live")]);
    const m = mount(withClient(world.client, <AgentLayer worldId="w_live" rooms={null} />));
    await settle();

    registerProbe("w_live", {
      agentAt: () => null,
      locate: (id) => (id === "B3" ? { x: 50, y: 80 } : id === "B4" ? { x: 300, y: 220 } : null),
    });

    act(() => world.push(ev("artifact.delivered", "A_l1", "art_pack")));
    await settle();

    const parcel = m.container.querySelector<HTMLElement>(".tw-parcel");
    expect(parcel).not.toBeNull();
    expect(parcel?.style.offsetPath).toContain("M 50 80 Q");
    expect(parcel?.style.offsetPath).toContain("300 220");
  });

  it("on world.completed: agents move to Dock, hopping is enabled, and confetti + dock hop burst", async () => {
    resetEvents();
    const world = fakeWorld(layout, [ev("world.started", "system", "w_live")]);
    const m = mount(withClient(world.client, <AgentLayer worldId="w_live" rooms={null} />));
    await settle();

    expect(m.container.querySelector('[data-testid="confetti"]')).toBeNull();
    expect(m.container.querySelector('[data-testid="dock-hop"]')).toBeNull();

    act(() => world.push(ev("world.completed", "A_dir", "w_live")));
    await settle();

    // Confetti bursts once
    const confetti = m.container.querySelector('[data-testid="confetti"]');
    expect(confetti).not.toBeNull();
    expect(confetti?.children.length).toBeGreaterThan(10);

    // Dock hop celebration is present
    const dockHop = m.container.querySelector('[data-testid="dock-hop"]');
    expect(dockHop).not.toBeNull();

    // Reducer & frame state: agents gather at the dock and have hopping: true
    let state = createInitialState(layout);
    state = applyEvent(state, ev("world.started", "system", "w_live"), layout);
    state = applyEvent(
      state,
      ev("agent.spawned", "A_dir", "A_l1", { role: "lead", post: "B1" }),
      layout,
    );
    state = applyEvent(state, ev("world.completed", "A_dir", "w_live"), layout);

    expect(state.status).toBe("completed");
    expect(state.agents.A_l1?.location).toBe("B4"); // Delivery Dock
    expect(standingAt(state, state.agents.A_l1 as never)).toBe("B4");

    const frame = frameOf(layout, state);
    expect(frame.agents.find((a) => a.id === "A_l1")?.hopping).toBe(true);
  });
});

describe("TW-5: FailureCard", () => {
  it("renders failure explanation, safe note, done and not done columns, credits note, and retry action", async () => {
    const onRetry = vi.fn();
    const failEvents = [
      ev("world.started", "system", "w_live"),
      ev("building.completed", "A_dir", "B1", { summary: "completed Plan" }),
      ev("world.failed", "system", "w_live", {
        step: "Flights",
        reason: "The airline site blocked automated search after 3 tries.",
        credits_used: 28,
        credits_cap: 120,
      }),
    ];

    const m = mount(
      <div data-park="">
        <FailureCard events={failEvents} onRetry={onRetry} />
      </div>,
    );
    await settle();

    const card = m.container.querySelector('[data-testid="world-failure-card"]');
    expect(card).not.toBeNull();
    expect(card?.getAttribute("role")).toBe("alert");

    // Header
    expect(card?.textContent).toContain("Stopped at Flights");
    expect(card?.textContent).toContain("world.failed");

    // Explanation
    expect(card?.textContent).toContain("The airline site blocked automated search after 3 tries.");

    // Safe note
    expect(card?.textContent).toContain("Nothing was sent or paid.");

    // DONE & NOT DONE columns
    expect(card?.textContent).toContain("DONE");
    expect(card?.textContent).toContain("Plan");
    expect(card?.textContent).toContain("NOT DONE");
    expect(card?.textContent).toContain("Flights");
    expect(card?.textContent).toContain("Budget sheet");

    // Credits note
    expect(card?.textContent).toContain("28 of 120 credits used.");

    // Retry action
    const tryBtn = m.container.querySelector<HTMLButtonElement>(".tw-fail-btn--pri");
    expect(tryBtn?.textContent).toContain("Try again");
    tryBtn?.click();
    expect(onRetry).toHaveBeenCalled();

    // Secondary action
    expect(m.container.textContent).toContain("Use a different flight site");
  });
});
