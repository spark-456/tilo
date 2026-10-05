// @vitest-environment happy-dom
import type { Layout } from "@tilo/contracts";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { reduce } from "../world/reducer";
import { Crew } from "./Crew";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const layout = LAYOUT_VILLAGE_BASIC as unknown as Layout;

async function crewAt(seq: number): Promise<HTMLElement> {
  const events = EVENTS_VILLAGE_BASIC.filter((e) => e.seq <= seq);
  const container = document.createElement("div");
  document.body.append(container);
  await act(async () => {
    createRoot(container).render(
      <Crew layout={layout} state={reduce(layout, events)} events={events} />,
    );
  });
  return container;
}

describe("PRD-18.3 S-14 hero crew: who has joined comes from the recorded events (HR-1)", () => {
  it("lists every agent of the layout by name, none joined before the first event", async () => {
    const items = [...(await crewAt(0)).querySelectorAll("li")];
    expect(items.map((li) => li.querySelector(".crew-name")?.textContent)).toEqual([
      "Director",
      "Lead",
      "Specialist 1",
      "Specialist 2",
      "Verifier",
    ]);
    expect(items.every((li) => li.getAttribute("data-joined") === "false")).toBe(true);
    expect(items.every((li) => li.textContent?.includes("Not joined"))).toBe(true);
  });

  it("marks an agent joined once it has spawned or acted, and says nothing for it", async () => {
    const items = [...(await crewAt(44)).querySelectorAll("li")];
    expect(items.every((li) => li.getAttribute("data-joined") === "true")).toBe(true);
    expect(items.some((li) => li.textContent?.includes("Not joined"))).toBe(false);
  });
});
