// @vitest-environment happy-dom
import type { Event } from "@tilo/contracts";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import type { TiloClient } from "../../api/client";
import {
  BrowserPanel,
  FRAME_UNAVAILABLE,
  GATED_LINE,
  REFUSAL_LINES,
  STOP_LINES,
  browserFrames,
  browserPictures,
  browserView,
  finishedLine,
} from "./BrowserPanel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const recorded = (seq: number, type: string, data: object) => ({ seq, type, data }) as Event;

const SESSION = "bs_01K7M000000000000000000000";
const BOX = { x: 200, y: 300, width: 100, height: 40 };
const started = (frame: string | null = "art_0") =>
  recorded(1, "browser.started", {
    session: SESSION,
    host: "en.wikipedia.org",
    frame: frame ? { artifact_id: frame, version: 1 } : null,
  });
/** A recorded browser.acted: `box` is the real target box a pointer action carries (absent for extract and navigate). */
const acted = (
  seq: number,
  kind: string,
  caption: string,
  frame: string,
  box: object | null = null,
  verdict = "done",
) =>
  recorded(seq, "browser.acted", {
    session: SESSION,
    step: seq - 1,
    kind,
    verdict,
    host: "en.wikipedia.org",
    frame: { artifact_id: frame, version: 1 },
    caption,
    ...(box ? { target_box: box } : {}),
  });

describe("DEMO-BROWSER-PANEL: cursor follows only recorded browser actions", () => {
  it("DEMO_BROWSER_cursor is drawn only for a pointer action with a recorded box, never for started, extract or navigate", () => {
    // Even a box on an extract or navigate event (it should never be sent) draws no cursor: those have no mouse.
    const frames = browserFrames([
      started(),
      acted(2, "navigate", "Opening a page", "art_1", BOX),
      acted(3, "extract", "Reading en.wikipedia.org", "art_2", BOX),
      acted(4, "click", "Clicking Japan", "art_3", BOX),
      acted(5, "type", "Typing in Search", "art_4", BOX),
      acted(6, "key", "Pressing Enter", "art_5", BOX),
      acted(7, "scroll", "Scrolling down", "art_6", BOX),
      acted(8, "click", "Clicking nothing", "art_7"),
    ]);
    expect(frames.map((f) => f.cursor !== null)).toEqual([
      false, // started
      false, // navigate
      false, // extract
      true, // click
      true, // type
      true, // key
      true, // scroll
      false, // a click with no recorded box
    ]);
    expect(frames[3]?.cursor).toEqual({ seq: 4, x: 250, y: 320, caption: "Clicking Japan" });
  });

  it("DEMO_BROWSER_cursor a refused action has none, a gated one with a box has", () => {
    const frames = browserFrames([
      started(),
      acted(2, "click", "Clicking Buy", "art_1", BOX, "refused"),
      acted(3, "click", "Clicking Pay", "art_2", BOX, "gated"),
    ]);
    expect(frames.map((f) => f.cursor?.seq ?? null)).toEqual([null, null, 3]);
  });

  it("DEMO_BROWSER_pictures a click, type or key step is a before (previous frame, cursor) then an after; the rest one", () => {
    const pictures = browserPictures(
      browserFrames([
        started(),
        acted(2, "click", "Clicking Japan", "art_1", BOX),
        acted(3, "scroll", "Scrolling down", "art_2", BOX),
        acted(4, "type", "Typing in Search", "art_3", BOX),
        acted(5, "extract", "Reading en.wikipedia.org", "art_4"),
      ]),
    );
    expect(pictures.map((p) => [p.step, p.artifactId, p.phase])).toEqual([
      [0, "art_0", null],
      [1, "art_0", "before"], // the page as it was when Tilo clicked
      [1, "art_1", "after"],
      [2, "art_2", null], // a scroll is one picture
      [3, "art_2", "before"],
      [3, "art_3", "after"],
      [4, "art_4", null],
    ]);
  });

  it("DEMO_BROWSER_pictures nothing is shown before its event is recorded", () => {
    const events = [started(), acted(2, "click", "Clicking Japan", "art_1", BOX)];
    const ids = (n: number) =>
      browserPictures(browserFrames(events.slice(0, n))).map((p) => p.artifactId);
    expect(ids(0)).toEqual([]);
    expect(ids(1)).toEqual(["art_0"]);
    expect(ids(2)).toEqual(["art_0", "art_0", "art_1"]);
    expect(browserFrames([started(null)])).toEqual([]);
  });

  it("keeps the session state from recorded events: a gated step, the host, a paused world", () => {
    const action = acted(2, "click", "Clicking Search", "art_second", BOX);
    const gated = recorded(3, "browser.acted", {
      session: SESSION,
      kind: "click",
      verdict: "gated",
      host: "en.wikipedia.org",
      target_box: { x: 500, y: 500, width: 20, height: 20 },
    });
    expect(browserView([started(), action]).session).toBe(SESSION);
    expect(browserView([started(), action, gated]).gated).toBe(true);
    expect(browserView([started(), action, gated]).host).toBe("en.wikipedia.org");
    expect(browserView([started(), action, recorded(4, "world.paused", {})]).paused).toBe(true);
    expect(
      browserView([started(), action, recorded(4, "browser.stopped", { session: SESSION })])
        .stopped,
    ).toBe(true);
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
    expect(node.querySelector('a[href^="https:"]')?.getAttribute("href")).toBe(
      "https://en.wikipedia.org/",
    );
    const stop = Array.from(node.querySelectorAll("button")).find(
      (button) => button.textContent === "Stop",
    );
    await act(async () => stop?.click());
    expect(stopBrowser).toHaveBeenCalledWith("w_demo", session);
    expect(node.textContent).toContain(GATED_LINE);
    expect(node.textContent).not.toContain(STOP_LINES.done);
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
    expect(node.textContent).not.toContain(STOP_LINES.done);
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
        kind: "click",
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
    // Following the newest shows the click's "after" picture, with the cursor where the mouse is now.
    expect(getBrowserFrame).toHaveBeenCalledWith("w_demo", "art_second");
    expect(node.querySelector("img")?.getAttribute("src")).toBe("blob:masked-frame");
    const cursor = node.querySelector('[data-testid="tilo-browser-cursor"]');
    expect(cursor?.getAttribute("data-event-seq")).toBe("2");
    expect(cursor?.getAttribute("data-picture")).toBe("after");
    expect(node.textContent).toContain("Step 2 of 2 · Clicking Search · after");
    await act(async () => root.unmount());
  });

  it("DEMO_BROWSER_pictures Earlier shows the click's before picture with the cursor, then the first page with none", async () => {
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:frame"),
    });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    const getBrowserFrame = vi.fn(async () => new Blob(["masked"], { type: "image/png" }));
    const client = { getBrowserFrame } as unknown as TiloClient;
    const events = [started(), acted(2, "click", "Clicking Japan", "art_1", BOX)];
    const node = document.createElement("div");
    const root = createRoot(node);
    await act(async () =>
      root.render(<BrowserPanel client={client} worldId="w_demo" events={events} replay={false} />),
    );
    const button = (name: string) =>
      Array.from(node.querySelectorAll("button")).find((b) => b.textContent === name);
    const cursor = () => node.querySelector('[data-testid="tilo-browser-cursor"]');
    const current = () =>
      node.querySelector('button[aria-current="step"]')?.getAttribute("aria-label");
    expect(current()).toBe("Step 2: Clicking Japan");
    await act(async () => button("Earlier")?.click());
    expect(getBrowserFrame).toHaveBeenLastCalledWith("w_demo", "art_0");
    expect(node.textContent).toContain("Step 2 of 2 · Clicking Japan · before");
    expect(cursor()?.getAttribute("data-picture")).toBe("before");
    expect(current()).toBe("Step 2: Clicking Japan"); // the step stays lit on either picture
    await act(async () => button("Earlier")?.click());
    expect(node.textContent).toContain("Step 1 of 2 · Opened en.wikipedia.org");
    expect(cursor()).toBeNull();
    await act(async () => button("Later")?.click());
    await act(async () => button("Later")?.click());
    expect(getBrowserFrame).toHaveBeenLastCalledWith("w_demo", "art_1");
    expect(button("Latest")).toBeUndefined(); // back on the newest picture: following it again
    await act(async () => root.unmount());
  });

  it("DEMO_BROWSER_pictures an extract step shows its picture with no cursor", async () => {
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:frame"),
    });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    const getBrowserFrame = vi.fn(async () => new Blob(["masked"], { type: "image/png" }));
    const events = [
      started(),
      acted(2, "click", "Clicking Japan", "art_1", BOX),
      acted(3, "extract", "Reading en.wikipedia.org", "art_2"),
    ];
    const node = document.createElement("div");
    const root = createRoot(node);
    await act(async () =>
      root.render(
        <BrowserPanel
          client={{ getBrowserFrame } as unknown as TiloClient}
          worldId="w_demo"
          events={events}
          replay={false}
        />,
      ),
    );
    expect(getBrowserFrame).toHaveBeenLastCalledWith("w_demo", "art_2");
    expect(node.textContent).toContain("Step 3 of 3 · Reading en.wikipedia.org");
    expect(node.querySelector('[data-testid="tilo-browser-cursor"]')).toBeNull();
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
    expect(node.textContent).toContain("Step 2 of 3 · Scrolling down");
    await act(async () => button("Earlier")?.click());
    expect(getBrowserFrame).toHaveBeenLastCalledWith("w_demo", "art_0");
    expect(button("Earlier")?.disabled).toBe(true);
    await act(async () => button("Latest")?.click());
    expect(getBrowserFrame).toHaveBeenLastCalledWith("w_demo", "art_2");
    expect(node.textContent).toContain(finishedLine(3));
    expect(node.querySelector('[data-phase="finished"]')?.textContent).toContain("Finished");
    await act(async () => root.unmount());
  });

  it("DEMO_BROWSER says in one plain sentence why the browser stopped and what to try", async () => {
    const session = "bs_01K7M000000000000000000000";
    const started = recorded(1, "browser.started", { session, host: "x.example", frame: null });
    const cases: [object[], string][] = [
      [
        [started, recorded(2, "browser.stopped", { session, outcome: "login_wall" })],
        STOP_LINES.login_wall,
      ],
      [
        [
          started,
          recorded(2, "browser.acted", {
            session,
            verdict: "refused",
            reason: "offsite_host",
            frame: null,
          }),
          recorded(3, "browser.stopped", { session, outcome: "error" }),
        ],
        REFUSAL_LINES.offsite_host,
      ],
      [
        [started, recorded(2, "browser.stopped", { session, outcome: "cap_steps" })],
        STOP_LINES.cap_steps,
      ],
    ];
    for (const [events, line] of cases) {
      const node = document.createElement("div");
      const root = createRoot(node);
      await act(async () =>
        root.render(
          <BrowserPanel
            client={{} as TiloClient}
            worldId="w_demo"
            events={events as Event[]}
            replay={false}
          />,
        ),
      );
      expect(node.textContent).toContain(line);
      await act(async () => root.unmount());
    }
    for (const line of [
      ...Object.values(STOP_LINES),
      ...Object.values(REFUSAL_LINES),
      GATED_LINE,
    ]) {
      expect(line.split(". ").length, line).toBe(1);
      expect(line.endsWith("."), line).toBe(true);
    }
  });

  it("DEMO_BROWSER shows itself on its own as a card in the map's corner, Expand takes the map over, and Back to map holds until the next session", async () => {
    const first = "bs_01K7M000000000000000000001";
    const second = "bs_01K7M000000000000000000002";
    const node = document.createElement("div");
    const root = createRoot(node);
    const render = (events: Event[]) =>
      act(async () =>
        root.render(
          <BrowserPanel
            client={{} as TiloClient}
            worldId="w_demo"
            events={events}
            replay={false}
            placement="takeover"
          />,
        ),
      );
    const opened = [recorded(1, "browser.started", { session: first, host: "en.wikipedia.org" })];
    await render(opened);
    const panel = () => node.querySelector('[data-testid="tilo-browser-panel"]');
    // The World stays in view: a solid card in the map's corner, not a takeover.
    expect(panel()?.className).toContain("tilo-bv--card");
    expect(panel()?.className).not.toContain("tilo-bv--takeover");
    expect(node.querySelector(".tilo-bv__address")?.textContent).toBe("en.wikipedia.org");
    const button = (name: string) =>
      Array.from(node.querySelectorAll("button")).find((b) => b.textContent?.startsWith(name));
    await act(async () => button("Expand")?.click());
    expect(panel()?.className).toContain("tilo-bv--takeover");
    expect(panel()?.className).not.toContain("tilo-bv--card");
    await act(async () => button("Shrink")?.click());
    expect(panel()?.className).toContain("tilo-bv--card");
    await act(async () => button("Back to map")?.click());
    expect(panel()).toBeNull();
    await act(async () => button("Show Tilo browser")?.click());
    expect(panel()).not.toBeNull();
    await act(async () => button("Back to map")?.click());
    await render([
      ...opened,
      recorded(2, "browser.started", { session: second, host: "en.wikipedia.org" }),
    ]);
    expect(panel()?.className).toContain("tilo-bv--card");
    await act(async () => root.unmount());
  });

  it("DEMO_BROWSER_window moves with the arrow keys on the grip, remembers its place, and Dock puts it back", async () => {
    window.localStorage.removeItem("tilo.browser.pos");
    const node = document.createElement("div");
    document.body.append(node);
    const root = createRoot(node);
    await act(async () =>
      root.render(
        <BrowserPanel
          client={{} as TiloClient}
          worldId="w_demo"
          events={[started()]}
          replay={false}
          placement="takeover"
        />,
      ),
    );
    const panel = () => node.querySelector<HTMLElement>('[data-testid="tilo-browser-panel"]');
    const grip = node.querySelector<HTMLButtonElement>('button[aria-label="Move the browser"]');
    const key = (name: string) =>
      act(async () => {
        grip?.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true }));
      });
    const left = () => Number.parseInt(panel()?.style.left ?? "", 10);
    expect(grip).not.toBeNull();
    expect(panel()?.getAttribute("data-floating")).toBeNull(); // docked over the map by default
    expect(Array.from(node.querySelectorAll("button")).map((b) => b.textContent)).not.toContain(
      "Dock",
    );
    await key("ArrowRight"); // the first press undocks it
    expect(panel()?.getAttribute("data-floating")).toBe("true");
    expect(panel()?.className).toContain("tilo-bv--floating");
    const first = left();
    await key("ArrowRight");
    expect(left() - first).toBe(16);
    await key("ArrowLeft");
    expect(left()).toBe(first);
    expect(JSON.parse(window.localStorage.getItem("tilo.browser.pos") ?? "null")).toMatchObject({
      left: first,
    });
    await key("Escape"); // other keys do not move it
    expect(left()).toBe(first);
    const dock = Array.from(node.querySelectorAll("button")).find((b) => b.textContent === "Dock");
    await act(async () => dock?.click());
    expect(panel()?.getAttribute("data-floating")).toBeNull();
    expect(window.localStorage.getItem("tilo.browser.pos")).toBeNull();
    expect(document.activeElement).toBe(grip);
    await act(async () => root.unmount());
    node.remove();
  });

  it("DEMO_BROWSER_window a saved place floats it on the next visit, and a broken save is ignored", async () => {
    const render = async (saved: string | null) => {
      if (saved === null) window.localStorage.removeItem("tilo.browser.pos");
      else window.localStorage.setItem("tilo.browser.pos", saved);
      const node = document.createElement("div");
      const root = createRoot(node);
      await act(async () =>
        root.render(
          <BrowserPanel
            client={{} as TiloClient}
            worldId="w_demo"
            events={[started()]}
            replay={false}
            placement="takeover"
          />,
        ),
      );
      const floating = node
        .querySelector('[data-testid="tilo-browser-panel"]')
        ?.getAttribute("data-floating");
      await act(async () => root.unmount());
      return floating;
    };
    expect(await render('{"left":40,"top":60}')).toBe("true");
    expect(await render("not json")).toBeNull();
    expect(await render('{"left":"x"}')).toBeNull();
    expect(await render(null)).toBeNull();
    window.localStorage.removeItem("tilo.browser.pos");
  });

  it("DEMO_BROWSER_window a phone-wide view takes the map area over, with no grip, drag, Dock or Expand", async () => {
    window.localStorage.setItem("tilo.browser.pos", '{"left":40,"top":60}');
    const wide = window.innerWidth;
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
    const node = document.createElement("div");
    const root = createRoot(node);
    await act(async () =>
      root.render(
        <BrowserPanel
          client={{} as TiloClient}
          worldId="w_demo"
          events={[started()]}
          replay={false}
          placement="takeover"
        />,
      ),
    );
    expect(node.querySelector('button[aria-label="Move the browser"]')).toBeNull();
    expect(node.querySelector('[data-floating="true"]')).toBeNull();
    const names = Array.from(node.querySelectorAll("button")).map((b) => b.textContent);
    expect(names).toContain("Back to map");
    expect(names).not.toContain("Dock");
    expect(names).not.toContain("Expand");
    expect(node.querySelector('[data-testid="tilo-browser-panel"]')?.className).toContain(
      "tilo-bv--takeover",
    );
    await act(async () => root.unmount());
    Object.defineProperty(window, "innerWidth", { configurable: true, value: wide });
    window.localStorage.removeItem("tilo.browser.pos");
  });

  it("DEMO_BROWSER_newtab opens the browser's own page in a new tab, except on that page and in a replay", async () => {
    const link = async (props: { placement?: "page"; replay?: boolean }) => {
      const node = document.createElement("div");
      const root = createRoot(node);
      await act(async () =>
        root.render(
          <BrowserPanel
            client={{} as TiloClient}
            worldId="w 1"
            events={[started()]}
            replay={props.replay ?? false}
            {...(props.placement ? { placement: props.placement } : {})}
          />,
        ),
      );
      const a = Array.from(node.querySelectorAll("a")).find(
        (x) => x.textContent === "Open in new tab",
      );
      await act(async () => root.unmount());
      return a;
    };
    const a = await link({});
    expect(a?.getAttribute("href")).toBe("/world/w%201/browser");
    expect(a?.getAttribute("target")).toBe("_blank");
    expect(a?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(await link({ placement: "page" })).toBeUndefined();
    expect(await link({ replay: true })).toBeUndefined();
  });

  it("DEMO_BROWSER has no control that cannot work: no Pause, and Stop only while the browser is live", async () => {
    const session = "bs_01K7M000000000000000000003";
    const client = { stopBrowser: vi.fn(async () => undefined) } as unknown as TiloClient;
    const started = recorded(1, "browser.started", { session, host: "x.example" });
    const names = async (events: Event[]) => {
      const node = document.createElement("div");
      const root = createRoot(node);
      await act(async () =>
        root.render(
          <BrowserPanel client={client} worldId="w_demo" events={events} replay={false} />,
        ),
      );
      const found = Array.from(node.querySelectorAll("button")).map((b) => b.textContent);
      const badge = node.querySelector(".tilo-bv__badge")?.textContent;
      await act(async () => root.unmount());
      return { found, badge };
    };
    const live = await names([started]);
    expect(live.found).toContain("Stop");
    expect(live.found).not.toContain("Pause");
    expect(live.badge).toBe("Live");
    const done = await names([
      started,
      recorded(2, "browser.stopped", { session, outcome: "done" }),
    ]);
    expect(done.found).not.toContain("Stop");
    expect(done.badge).toBe("Finished");
  });

  it("DEMO_BROWSER a click enlarges the picture to full size, and Escape closes it", async () => {
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:frame"),
    });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    const getBrowserFrame = vi.fn(async () => new Blob(["masked"], { type: "image/png" }));
    const session = "bs_01K7M000000000000000000004";
    const node = document.createElement("div");
    document.body.append(node);
    const root = createRoot(node);
    await act(async () =>
      root.render(
        <BrowserPanel
          client={{ getBrowserFrame } as unknown as TiloClient}
          worldId="w_demo"
          events={[
            recorded(1, "browser.started", {
              session,
              host: "x.example",
              frame: { artifact_id: "a" },
            }),
          ]}
          replay={false}
        />,
      ),
    );
    const enlarge = node.querySelector<HTMLButtonElement>(
      'button[aria-label="Enlarge the picture"]',
    );
    await act(async () => enlarge?.click());
    expect(node.querySelector("dialog img")?.getAttribute("src")).toBe("blob:frame");
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(node.querySelector("dialog")).toBeNull();
    await act(async () => root.unmount());
    node.remove();
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
