// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import { FixtureClient } from "../api/fixtureClient";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { LevelsPanel } from "./LevelsPanel";
import { ReplayScrubber } from "./ReplayScrubber";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function mount(node: React.ReactNode): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.append(container);
  const silent = new FixtureClient();
  silent.subscribeEvents = () => () => undefined; // the replayed events are the only run
  await act(async () => {
    createRoot(container).render(<ClientProvider client={silent}>{node}</ClientProvider>);
  });
  await act(async () => {
    await new Promise((done) => setTimeout(done, 20)); // the layout arrives on a later tick
  });
  return container;
}

describe("PRD-18.3 S-04 levels panel (FR-WLD-08 replay point): the layout and the replayed events", () => {
  it("names the size and counts, and one card per level linking to its Inspect page", async () => {
    const panel = (
      await mount(<LevelsPanel worldId="w_village_basic" replayed={EVENTS_VILLAGE_BASIC} />)
    ).querySelector('[data-testid="levels-panel"]');
    expect(panel?.textContent).toContain("Village");
    expect(panel?.textContent).toContain("5 agents · 5 buildings · 1 gate");
    const card = panel?.querySelector("a.level-card");
    expect(card?.getAttribute("href")).toBe("/world/w_village_basic/inspect/L1");
    expect(card?.textContent).toContain("L1");
    expect(card?.textContent).toContain("Inbox");
    expect(card?.textContent).toContain("100%");
    expect(card?.querySelector("progress")?.getAttribute("value")).toBe("100");
  });

  it("follows the replay: an early point shows an unfinished level and its latest line", async () => {
    const early = EVENTS_VILLAGE_BASIC.filter((e) => e.seq <= 30);
    const card = (
      await mount(<LevelsPanel worldId="w_village_basic" replayed={early} />)
    ).querySelector("a.level-card");
    expect(card?.textContent).toContain("0%");
    expect(card?.getAttribute("data-active")).toBe("true");
    expect(card?.textContent).not.toContain("complete");
  });
});

describe("PRD-18.3 S-04 scrubber marks: drawn only for a finished run", () => {
  it("draws one mark per decision or finish, none while the run is going", async () => {
    const finished = await mount(
      <ReplayScrubber worldId="w_marks" events={EVENTS_VILLAGE_BASIC} finished fixture />,
    );
    const marks = [...finished.querySelectorAll('[data-testid="scrub-marks"] i')];
    expect(marks.map((m) => m.getAttribute("data-kind"))).toEqual(["decision", "done", "done"]);
    expect(marks.every((m) => (m as HTMLElement).style.getPropertyValue("--at") !== "")).toBe(true);
    const going = await mount(
      <ReplayScrubber worldId="w_marks2" events={EVENTS_VILLAGE_BASIC} finished={false} fixture />,
    );
    expect(going.querySelectorAll('[data-testid="scrub-marks"] i')).toHaveLength(0);
  });
});
