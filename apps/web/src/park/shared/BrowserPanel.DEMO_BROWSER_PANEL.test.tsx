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

  it("DEMO_BROWSER steps back and forth through every recorded frame after the run, as display state", async () => {
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:frame"),
    });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    const getBrowserFrame = vi.fn(async () => new Blob(["masked"], { type: "image/png" }));
    const client = { getBrowserFrame } as unknown as TiloClient;
    const session = "bs_01K7M000000000000000000000";
    const box = { x: 0, y: 0, width: 1200, height: 800 };
    const events = [
      recorded(1, "browser.started", {
        session,
        host: "en.wikipedia.org",
        frame: { artifact_id: "art_0" },
      }),
      recorded(2, "browser.acted", {
        session,
        verdict: "done",
        kind: "scroll",
        frame: { artifact_id: "art_1" },
        target_box: box,
        caption: "Scrolling down",
      }),
      recorded(3, "browser.acted", {
        session,
        verdict: "done",
        kind: "extract",
        frame: { artifact_id: "art_2" },
        target_box: box,
        caption: "Reading en.wikipedia.org",
      }),
      recorded(4, "browser.stopped", { session, outcome: "done", steps: 2 }),
    ];
    const node = document.createElement("div");
    const root = createRoot(node);
    await act(async () =>
      root.render(<BrowserPanel client={client} worldId="w_demo" events={events} replay={false} />),
    );
    const button = (name: string) =>
      Array.from(node.querySelectorAll("button")).find((b) => b.textContent === name);
    expect(getBrowserFrame).toHaveBeenLastCalledWith("w_demo", "art_2");
    expect(button("Later")?.disabled).toBe(true);
    await act(async () => button("Earlier")?.click());
    expect(getBrowserFrame).toHaveBeenLastCalledWith("w_demo", "art_1");
    expect(node.textContent).toContain("Frame 2 of 3: Scrolling down");
    await act(async () => button("Earlier")?.click());
    expect(getBrowserFrame).toHaveBeenLastCalledWith("w_demo", "art_0");
    expect(button("Earlier")?.disabled).toBe(true);
    await act(async () => button("Latest")?.click());
    expect(getBrowserFrame).toHaveBeenLastCalledWith("w_demo", "art_2");
    expect(node.textContent).toContain("Browser stopped");
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
