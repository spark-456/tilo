// @vitest-environment happy-dom
// WORLD-STATUS-1 (FR-WLD-05, FR-WLD-09; HR-1, HR-5): on a finished world's live view the side panel derives from the
// same recorded events the header uses. A completed run shows its workstreams finished and its level at 100%; a run
// whose events recorded no building or level progress shows no percentage; "Level One" is never worded "Level Level One".
import type { Event, Layout } from "@tilo/contracts";
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import { FixtureClient } from "../api/fixtureClient";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { levelRows } from "../world/levels";
import { reduce } from "../world/reducer";
import { StageRail } from "./StageRail";
import { levelTitle } from "./text";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  document.body.replaceChildren();
});

const layout = structuredClone(LAYOUT_VILLAGE_BASIC) as unknown as Layout;
const level = layout.semantic.levels[0];
if (!level) throw new Error("fixture has a level");
level.name = "Level One";
for (const d of level.districts)
  d.buildings.forEach((b, i) => Object.assign(b, { name: `Workstream ${i + 1}` }));

/** The recorded run with no building, district or level events: what a real run recorded. */
const BARE = (EVENTS_VILLAGE_BASIC as unknown as Event[]).filter(
  (e) => !/^(building|district|level)\./.test(e.type),
);
const upTo = (type: string): Event[] => {
  const i = BARE.findIndex((e) => e.type === type);
  return i < 0 ? BARE : BARE.slice(0, i);
};

class OneLayout extends FixtureClient {
  async getLayout(): Promise<Layout> {
    return layout;
  }
}

async function draw(events: Event[]): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () =>
    root?.render(
      <ClientProvider client={new OneLayout()}>
        <StageRail worldId="w_village_basic" replayed={events} />
      </ClientProvider>,
    ),
  );
  await act(async () => new Promise((r) => setTimeout(r, 20)));
  return container;
}

describe("FR_WLD_05 WORLD-STATUS-1 the stage side panel follows the recorded run", () => {
  it("FR_WLD_09 levelTitle never doubles the word Level", () => {
    expect(levelTitle("Level One")).toBe("Level One");
    expect(levelTitle("level 2")).toBe("level 2");
    expect(levelTitle("Inbox")).toBe("Level Inbox");
  });

  it("FR_WLD_05 a completed run shows its workstreams finished and its level at 100%", async () => {
    const view = await draw(BARE);
    const text = view.textContent ?? "";
    expect(text).not.toContain("Level Level");
    expect(text).toContain("Level One");
    expect(text).toContain("100%");
    expect(text).not.toContain("Not planned yet");
    expect(text).toContain("Finished");
  });

  it("FR_WLD_09 a started run with no recorded building progress shows no percentage", async () => {
    const events = upTo("world.completed");
    const view = await draw(events);
    expect(view.textContent).not.toMatch(/\d+%/);
    expect(view.textContent).not.toContain("Finished");
  });

  it("FR_WLD_05 levelRows says whether its percentage rests on a recorded event", () => {
    const done = levelRows(layout, reduce(layout, BARE), BARE);
    expect(done[0]).toMatchObject({ percent: 100, measured: true });
    const mid = upTo("world.completed");
    const running = levelRows(layout, reduce(layout, mid), mid);
    expect(running[0]).toMatchObject({ percent: 0, measured: false });
  });
});
