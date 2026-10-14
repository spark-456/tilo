// @vitest-environment happy-dom
// OLD-UI-OUT-2: a world's lenses and the Needs-you page render as Park pages from their address alone: the same
// recorded run, the lens tabs, the shared selection bar, and the way back to the world's overview.
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import { FixtureClient } from "../api/fixtureClient";
import { FIXTURE_WORLD_ID } from "../api/fixtures/derived";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { forgetWorld } from "../world/lastWorld";
import { select } from "../world/selection";
import WorldViewApp from "./WorldViewApp";
import { type ViewRoute, parseViewPath } from "./routes";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;

function finishedClient(): FixtureClient {
  const client = new FixtureClient();
  client.subscribeEvents = (_world, onEvent) => {
    for (const e of EVENTS_VILLAGE_BASIC) onEvent(e);
    return () => undefined;
  };
  return client;
}

async function show(path: string): Promise<HTMLElement> {
  window.history.pushState({}, "", path);
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root?.render(
      <ClientProvider client={finishedClient()}>
        <WorldViewApp route={parseViewPath(path) as ViewRoute} />
      </ClientProvider>,
    );
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 25));
  });
  return container;
}

beforeEach(() => {
  forgetWorld();
  select(FIXTURE_WORLD_ID, null);
});
afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.replaceChildren();
  window.history.pushState({}, "", "/");
});

const W = `/world/${FIXTURE_WORLD_ID}`;

describe("OLD_UI_OUT_2 world views are Park pages", () => {
  it.each([
    [`${W}/story`, "story-lens", "Story"],
    [`${W}/trace`, "trace-lens", "Trace"],
    [`${W}/delivery`, "delivery", "Delivery"],
    [`${W}/inspect/B1`, "inspect-panel", null],
  ] as const)("%s draws %s inside the lens frame", async (path, testid, title) => {
    const c = await show(path);
    expect(c.querySelector(`[data-testid="${testid}"]`), path).not.toBeNull();
    // the way back to the world's overview, the Park address
    expect(c.querySelector("a.park-view-back")?.getAttribute("href")).toBe(W);
    if (title) expect(c.querySelector("h1")?.textContent).toBe(title);
    // the frame is the Park one: no old shell furniture
    expect(c.querySelector(".screen-page, .screen-body, .app-shell")).toBeNull();
  });

  it("the lens tabs link the three lenses and the delivery, marking the current one", async () => {
    const c = await show(`${W}/story`);
    const tabs = [...c.querySelectorAll<HTMLAnchorElement>('nav[aria-label="Lens"] a')];
    expect(tabs.map((a) => a.getAttribute("href"))).toEqual([
      `${W}/stage`,
      `${W}/story`,
      `${W}/trace`,
      `${W}/delivery`,
    ]);
    expect(tabs.filter((a) => a.getAttribute("aria-current") === "page")).toHaveLength(1);
    expect(tabs[1]?.getAttribute("aria-current")).toBe("page");
  });

  it("the stage lens draws the stage, the replay dock and the side panels", async () => {
    const c = await show(`${W}/stage`);
    expect(c.querySelector('[data-testid="world-stage-view"]')).not.toBeNull();
    expect(c.querySelector('[data-testid="stage-frame"]')?.tagName).toBe("SECTION");
    expect(c.querySelector('[data-testid="replay-scrubber"]')).not.toBeNull();
    expect(c.querySelector('[data-testid="world-hud"]')).not.toBeNull();
    expect(c.querySelector('[data-testid="pause-slot"]')).not.toBeNull();
  });

  it("an unknown world is Not found, never another world's run", async () => {
    const client = new FixtureClient();
    window.history.pushState({}, "", "/world/bogus/story");
    const container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ClientProvider client={client}>
          <WorldViewApp route={parseViewPath("/world/bogus/story") as ViewRoute} />
        </ClientProvider>,
      );
    });
    expect(container.querySelector('[data-testid="not-found"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="story-lens"]')).toBeNull();
  });

  it("the Needs-you pages draw their own testids with the Park heading", async () => {
    for (const [path, testid, h1] of [
      ["/needs-you", "needs-you", "Needs you"],
      ["/needs-you/gate", "gate-sheet-page", "Approval gate"],
      ["/needs-you/consent", "consent-sheet-page", "Connection consent"],
    ] as const) {
      const c = await show(path);
      expect(c.querySelector(`[data-testid="${testid}"]`), path).not.toBeNull();
      expect(c.querySelector("h1")?.textContent, path).toBe(h1);
      act(() => root?.unmount());
      document.body.replaceChildren();
    }
  });
});
