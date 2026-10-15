// @vitest-environment happy-dom
// UI-STUDIO-2 Tilo bubble (design/studio-v2 "Tilo S Bubble"): a drag moves it and the place is kept in browser storage
// (blocked storage falls back to the corner), the arrow keys move it too, a drag is not an open, and the compact chat
// asks over the real Quick answer path.
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler } from "../../../test-support/park/appHarness";
import { cleanup, mount, q, qa } from "../../../test-support/park/componentsHarness";
import { settle, textOf } from "../../../test-support/park/homeHarness";
import { liveSourced } from "../../../test-support/park/liveHomeHarness";
import type { Api } from "../api/index";
import type { PageId } from "../app/AppCtx";
import { ParkProvider } from "../app/context";
import { readBubblePos } from "../chat/displayPrefs";
import { TiloBubble, clampPos } from "./TiloBubble";

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

async function mountBubble(api: Api = fakeApi(), go = vi.fn()) {
  const m = mount(
    <ParkProvider
      api={api}
      navigate={vi.fn()}
      schedule={fakeScheduler().schedule}
      viewport={{ vw: 1440, vh: 900 }}
    >
      <TiloBubble page={"home" as PageId} vw={1440} vh={900} go={go} />
    </ParkProvider>,
  );
  await settle();
  return { el: m.container, go };
}
const bubble = () => q<HTMLButtonElement>(document.body, "button.park-bubble");
const panel = () => document.body.querySelector('dialog[aria-label="Your Tilo"]');
function pointer(type: string, x: number, y: number) {
  act(() => {
    bubble().dispatchEvent(
      new MouseEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0 }),
    );
  });
}

describe("STUDIO_2 bubble: it can be put anywhere and stays there", () => {
  it("STUDIO_2 bubble a drag moves it, keeps the place in storage and does not open the chat", async () => {
    await mountBubble();
    expect(bubble().style.right).toBe("40px");
    expect(bubble().style.bottom).toBe("40px");
    pointer("pointerdown", 1000, 800);
    pointer("pointermove", 900, 600);
    pointer("pointerup", 900, 600);
    act(() => bubble().click()); // the click a browser sends after the drag
    expect(bubble().style.right).toBe("140px");
    expect(bubble().style.bottom).toBe("240px");
    expect(readBubblePos()).toEqual({ right: 140, bottom: 240 });
    expect(panel()).toBeNull();
    cleanup();
    await mountBubble();
    expect(bubble().style.right).toBe("140px"); // the place survives a reload
  });

  it("STUDIO_2 bubble a short press is a click that opens the chat, not a drag", async () => {
    await mountBubble();
    pointer("pointerdown", 1000, 800);
    pointer("pointermove", 1002, 801);
    pointer("pointerup", 1002, 801);
    act(() => bubble().click());
    expect(panel()).not.toBeNull();
    expect(readBubblePos()).toBeNull();
    expect(bubble().getAttribute("aria-expanded")).toBe("true");
  });

  it("STUDIO_2 bubble arrow keys move it and it never leaves the screen", async () => {
    await mountBubble();
    act(() => {
      bubble().dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));
    });
    expect(readBubblePos()).toEqual({ right: 56, bottom: 40 });
    expect(clampPos({ right: -50, bottom: 5000 }, 1440, 900)).toEqual({ right: 8, bottom: 828 });
  });

  it("STUDIO_2 bubble blocked storage falls back to the corner without an error", async () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new Error("blocked");
    });
    await mountBubble();
    expect(bubble().style.right).toBe("40px");
    pointer("pointerdown", 1000, 800);
    pointer("pointermove", 900, 800);
    pointer("pointerup", 900, 800);
    expect(bubble().style.right).toBe("140px"); // moved for this visit, nothing thrown
  });
});

describe("STUDIO_2 bubble: the compact chat is the real Quick answer path", () => {
  it("STUDIO_2 bubble asks over Quick and shows the served answer, Escape closes it", async () => {
    const startWorld = vi.fn(async () => ({
      data: { kind: "answered", text: "Three steps to go.", cost: null },
      source: "live",
    }));
    await mountBubble(liveSourced({ startWorld } as unknown as Partial<Api>));
    act(() => bubble().click());
    const input = q<HTMLInputElement>(document.body, "dialog input");
    act(() => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      set?.call(input, "What is left?");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => q<HTMLButtonElement>(document.body, 'dialog button[aria-label="Send"]').click());
    await settle();
    expect(startWorld).toHaveBeenCalledWith("quick", "What is left?", "quick");
    expect(textOf(q(document.body, 'dialog [role="log"]'))).toContain("Three steps to go.");
    expect(textOf(q(document.body, "dialog"))).not.toContain("Sample answer");
    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(panel()).toBeNull();
  });

  it("STUDIO_2 bubble the open-chat button goes to the Chat page", async () => {
    const { go } = await mountBubble();
    act(() => bubble().click());
    act(() =>
      q<HTMLButtonElement>(document.body, 'button[aria-label="Open the full chat"]').click(),
    );
    expect(go).toHaveBeenCalledWith("chat");
    expect(qa(document.body, "dialog")).toHaveLength(0);
  });
});
