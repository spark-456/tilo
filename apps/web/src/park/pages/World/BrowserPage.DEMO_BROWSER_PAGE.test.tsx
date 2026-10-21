// @vitest-environment happy-dom
// DEMO-BROWSER: Tilo's browser as a page of its own (/world/:id/browser, "Open in new tab"): the address resolves, the
// page reads the same recorded events as the World page (the signed-in world client, owner only), says plainly that the
// browser has not opened yet, and shows it full page the moment `browser.started` is recorded. No network is touched.
import type { Event } from "@tilo/contracts";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeScheduler, stubApp } from "../../../../test-support/park/appHarness";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import {
  liveWorldsApi,
  pageText,
  settle,
  spiedApi,
} from "../../../../test-support/park/worldHarness";
import { HttpClient } from "../../../api/http";
import type { Api } from "../../api/index";
import { ParkProvider } from "../../app/context";
import { browserPath, isParkPath, parseBrowserPath, parseParkPath } from "../../app/router";
import { BROWSER_NOT_OPEN, BrowserPage } from "./BrowserPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const SESSION = "bs_01K7M000000000000000000000";
const recorded = (seq: number, type: string, data: object) => ({ seq, type, data }) as Event;

/** A world client whose event feed the test drives; it never touches the network. */
function rig(id: string, api: Api = liveWorldsApi(), withClient = true) {
  const feed: { push: (e: Event) => void } = { push: () => undefined };
  const client = new HttpClient({
    baseUrl: "http://localhost:0",
    fetch: async () => new Response("{}", { status: 404 }),
  });
  client.subscribeEvents = (_world, onEvent) => {
    feed.push = onEvent;
    return () => undefined;
  };
  const m = mount(
    <ParkProvider
      api={api}
      worldClient={withClient ? client : null}
      navigate={vi.fn()}
      schedule={fakeScheduler().schedule}
      viewport={{ vw: 1440, vh: 900 }}
    >
      <BrowserPage app={stubApp("world", { params: { id } })} worldId={id} />
    </ParkProvider>,
  );
  return { m, feed };
}

describe("DEMO_BROWSER_route the browser's own address", () => {
  it("DEMO_BROWSER_route /world/:id/browser resolves to the browser page and is a Park address", () => {
    expect(browserPath("w_here")).toBe("/world/w_here/browser");
    expect(browserPath("a b/c")).toBe("/world/a%20b%2Fc/browser");
    for (const [path, worldId] of [
      ["/world/w_here/browser", "w_here"],
      ["/world/w_here/browser/", "w_here"],
      ["/park/world/w_here/browser", "w_here"],
      ["/world/a%20b/browser", "a b"],
    ] as const) {
      expect(parseBrowserPath(path), path).toEqual({ worldId });
      expect(isParkPath(path), path).toBe(true);
      expect(parseParkPath(path, ""), path).toBeNull(); // not one of the shell's pages: the shell routes it itself
    }
    for (const path of [
      "/world/w_here",
      "/world/w_here/browser/more",
      "/world/%E0/browser",
      "/world//browser",
      "/world/w_here/stage",
      "/world/w_here/app/quiz",
    ]) {
      expect(parseBrowserPath(path), path).toBeNull();
    }
    // What was already under /world/:id keeps its owner.
    expect(isParkPath("/world/w_here/stage")).toBe(false);
    expect(parseParkPath("/world/w_here", "")?.page).toBe("world");
  });
});

describe("DEMO_BROWSER_page the browser as a page of its own", () => {
  it("DEMO_BROWSER_page says plainly the browser has not opened yet, then shows it live when it does", async () => {
    const { m, feed } = rig("hires");
    await settle();
    expect(pageText(m.container)).toContain(BROWSER_NOT_OPEN);
    expect(m.container.querySelector('[data-testid="tilo-browser-panel"]')).toBeNull();

    await act(async () => {
      feed.push(
        recorded(1, "browser.started", { session: SESSION, host: "en.wikipedia.org", frame: null }),
      );
    });
    const panel = m.container.querySelector('[data-testid="tilo-browser-panel"]');
    expect(panel).not.toBeNull();
    expect(pageText(m.container)).not.toContain(BROWSER_NOT_OPEN);
    expect(panel?.querySelector(".tilo-bv__badge")?.textContent).toBe("Live");
    expect(panel?.querySelector(".tilo-bv__address")?.textContent).toBe("en.wikipedia.org");
  });

  it("DEMO_BROWSER_page is the full-page placement: no map controls, no drag, no Dock, no second new tab", async () => {
    const { m, feed } = rig("hires");
    await settle();
    await act(async () => {
      feed.push(recorded(1, "browser.started", { session: SESSION, host: "en.wikipedia.org" }));
    });
    const panel = m.container.querySelector<HTMLElement>('[data-testid="tilo-browser-panel"]');
    expect(panel?.className).toContain("tilo-bv--page");
    const names = Array.from(panel?.querySelectorAll("button, a") ?? []).map((e) => e.textContent);
    expect(names).toContain("Stop");
    for (const gone of ["Back to map", "Dock", "Open in new tab"])
      expect(names).not.toContain(gone);
    expect(panel?.querySelector('button[aria-label="Move the browser"]')).toBeNull();
    expect(m.container.querySelector("h1")?.textContent).toBe("Tilo browser");
  });

  it("DEMO_BROWSER_page an unknown world, or a session with no signed-in client, is Page not found", async () => {
    const unknown = rig("w_nobody");
    await settle();
    expect(pageText(unknown.m.container)).toContain("Page not found");
    expect(unknown.m.container.querySelector('[data-testid="park-page-browser"]')).toBeNull();
    cleanup();
    // The fixture Api (a demo or a sample) has no run behind any id.
    const sample = rig("hires", spiedApi());
    await settle();
    expect(pageText(sample.m.container)).toContain("Page not found");
    cleanup();
    const signedOut = rig("hires", liveWorldsApi(), false);
    await settle();
    expect(pageText(signedOut.m.container)).toContain("Page not found");
  });

  it("DEMO_BROWSER_page says the world data is unavailable when the list cannot be read", async () => {
    const api = liveWorldsApi();
    api.getWorlds.mockRejectedValue(new Error("offline"));
    const { m } = rig("hires", api);
    await settle();
    expect(pageText(m.container)).toContain("World data is unavailable");
    expect(pageText(m.container)).not.toContain("Page not found");
  });
});
