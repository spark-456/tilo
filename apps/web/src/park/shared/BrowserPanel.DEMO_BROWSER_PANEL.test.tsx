// @vitest-environment happy-dom
import type { Event } from "@tilo/contracts";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import type { TiloClient } from "../../api/client";
import { BrowserPanel, FRAME_UNAVAILABLE, browserView } from "./BrowserPanel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const recorded = (seq: number, type: string, data: object) => ({ seq, type, data }) as Event;

describe("DEMO-BROWSER-PANEL: cursor follows only recorded browser actions", () => {
  it("ignores a start frame and moves only when an action event has a target box", () => {
    const start = recorded(1, "browser.started", {
      session: "bs_01K7M000000000000000000000",
      frame: { artifact_id: "art_first", version: 1 },
    });
    const action = recorded(2, "browser.acted", {
      session: "bs_01K7M000000000000000000000",
      frame: { artifact_id: "art_second", version: 1 },
      verdict: "done",
      target_box: { x: 200, y: 300, width: 100, height: 40 },
      caption: "Clicking Search",
    });
    expect(browserView([start]).cursor).toBeNull();
    expect(browserView([start, action]).cursor?.caption).toBe("Clicking Search");
    expect(browserView([start, action]).frame).toBe("art_second");
    expect(browserView([start, action, recorded(3, "browser.stopped", {})]).cursor?.seq).toBe(2);
    const gated = recorded(3, "browser.acted", {
      session: "bs_01K7M000000000000000000000",
      verdict: "gated",
      host: "en.wikipedia.org",
      target_box: { x: 500, y: 500, width: 20, height: 20 },
    });
    expect(browserView([start, action, gated]).cursor?.seq).toBe(2);
    expect(browserView([start, action, gated]).gated).toBe(true);
    expect(browserView([start, action, gated]).host).toBe("en.wikipedia.org");
    expect(browserView([start, action, recorded(4, "world.paused", {})]).paused).toBe(true);
  });

  it("shows a person handoff and sends Stop without claiming completion before its event", async () => {
    const stopBrowser = vi.fn(async () => undefined);
    const client = {
      stopBrowser,
      pauseWorld: vi.fn(async () => undefined),
    } as unknown as TiloClient;
    const session = "bs_01K7M000000000000000000000";
    const events = [
      recorded(1, "browser.started", { session, host: "en.wikipedia.org", frame: null }),
      recorded(2, "browser.acted", {
        session,
        verdict: "gated",
        host: "en.wikipedia.org",
        frame: null,
      }),
    ];
    const node = document.createElement("div");
    const root = createRoot(node);
    await act(async () =>
      root.render(<BrowserPanel client={client} worldId="w_demo" events={events} replay={false} />),
    );
    expect(node.querySelector("a")?.getAttribute("href")).toBe("https://en.wikipedia.org/");
    const stop = Array.from(node.querySelectorAll("button")).find(
      (button) => button.textContent === "Stop",
    );
    await act(async () => stop?.click());
    expect(stopBrowser).toHaveBeenCalledWith("w_demo", session);
    expect(node.textContent).toContain("Waiting for you");
    expect(node.textContent).not.toContain("Browser stopped");
    await act(async () => root.unmount());
  });

  it("labels Stop as a request until browser.stopped is recorded", async () => {
    const stopBrowser = vi.fn(async () => undefined);
    const client = { stopBrowser } as unknown as TiloClient;
    const session = "bs_01K7M000000000000000000000";
    const node = document.createElement("div");
    const root = createRoot(node);
    await act(async () =>
      root.render(
        <BrowserPanel
          client={client}
          worldId="w_demo"
          events={[recorded(1, "browser.started", { session })]}
          replay={false}
        />,
      ),
    );
    const stop = Array.from(node.querySelectorAll("button")).find(
      (button) => button.textContent === "Stop",
    );
    await act(async () => stop?.click());
    expect(node.textContent).toContain("Stopping");
    expect(node.textContent).not.toContain("Browser stopped");
    await act(async () => root.unmount());
  });

  it("loads only an event's masked frame and places the cursor at its recorded box", async () => {
    const create = vi.fn(() => "blob:masked-frame");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    const getBrowserFrame = vi.fn(async () => new Blob(["masked"], { type: "image/png" }));
    const client = { getBrowserFrame } as unknown as TiloClient;
    const session = "bs_01K7M000000000000000000000";
    const events = [
      recorded(1, "browser.started", {
        session,
        host: "en.wikipedia.org",
        frame: { artifact_id: "art_first" },
      }),
      recorded(2, "browser.acted", {
        session,
        verdict: "done",
        frame: { artifact_id: "art_second" },
        target_box: { x: 200, y: 300, width: 100, height: 40 },
        caption: "Clicking Search",
      }),
    ];
    const node = document.createElement("div");
    const root = createRoot(node);
    await act(async () =>
      root.render(<BrowserPanel client={client} worldId="w_demo" events={events} replay={false} />),
    );
    expect(getBrowserFrame).toHaveBeenCalledWith("w_demo", "art_second");
    expect(node.querySelector("img")?.getAttribute("src")).toBe("blob:masked-frame");
    expect(
      node.querySelector('[data-testid="tilo-browser-cursor"]')?.getAttribute("data-event-seq"),
    ).toBe("2");
    expect(node.textContent).toContain("Clicking Search");
    await act(async () => root.unmount());
  });

  it("DEMO_BROWSER says a frame the server will not serve could not be shown, never loads forever", async () => {
    const getBrowserFrame = vi.fn(async () => {
      throw new Error("404");
    });
    const client = { getBrowserFrame } as unknown as TiloClient;
    const session = "bs_01K7M000000000000000000000";
    const events = [
      recorded(1, "browser.started", {
        session,
        host: "en.wikipedia.org",
        frame: { artifact_id: "art_x" },
      }),
    ];
    const node = document.createElement("div");
    const root = createRoot(node);
    await act(async () =>
      root.render(<BrowserPanel client={client} worldId="w_demo" events={events} replay={false} />),
    );
    expect(getBrowserFrame).toHaveBeenCalledWith("w_demo", "art_x");
    expect(node.textContent).toContain(FRAME_UNAVAILABLE);
    expect(node.textContent).not.toContain("Loading recorded frame");
    await act(async () => root.unmount());
  });
});
