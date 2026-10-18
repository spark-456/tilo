// @vitest-environment happy-dom
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { AgentStats } from "../../world/agentStats";
import { AgentCard } from "./AgentCard";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

const SAMPLE_STATS: AgentStats = {
  id: "A_s1",
  name: "Specialist Kai",
  role: "Specialist",
  rank: "specialist",
  district: "Research",
  at: { id: "B1", name: "Science Lab" },
  task: "Gather requirements",
  unitsDone: 3,
  tools: ["gmail.search", "drive.read"],
  workCalls: 5,
  credits: 4.2,
  said: [
    {
      seq: 1,
      ts: "2026-10-16T09:00:00Z",
      kind: "handoff",
      from: "A_s1",
      to: "A_l1",
      text: "Ready for review",
      detail: [],
      where: "B1",
      room: null,
      turn: null,
      credits: 1,
    },
  ],
  status: "working",
  order: 1, // Blue (#3F7FE0)
};

describe("TW-2 AgentCard & AgentPanel", () => {
  it("renders AgentCard with AgentSprite and color swatch", () => {
    act(() => {
      root.render(<AgentCard stats={SAMPLE_STATS} at={{ x: 100, y: 150 }} />);
    });
    const card = container.querySelector('[data-testid="agent-card"]');
    expect(card).not.toBeNull();

    // Sprite is rendered
    const sprite = card?.querySelector(".tw-sprite");
    expect(sprite).not.toBeNull();

    // Name and role are rendered
    expect(card?.textContent).toContain("Specialist Kai");
    expect(card?.textContent).toContain("Specialist");

    // Swatch with color name "Blue" is rendered
    expect(card?.textContent).toContain("Blue · on map & chat");

    // Units, steps, credits
    expect(card?.textContent).toContain("3");
    expect(card?.textContent).toContain("5");
    expect(card?.textContent).toContain("4.2");
  });
});
