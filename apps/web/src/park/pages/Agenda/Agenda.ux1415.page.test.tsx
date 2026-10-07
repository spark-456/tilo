// @vitest-environment happy-dom
// FR-UX-14 / FR-UX-15 gaps on the Agenda (supplement 1.6 rows 72-73): the free slots are static dashed ghosts
// (no pulse: a looping pulse is not on the honesty allowlist, BQ-UX15-1) that are named, big enough to hit,
// and the booking goes through the one Api method `bookSlot`, only after a tap; a refused booking is an honest
// "Not connected yet", never a pin, an event or a fake success. Block it is local Park state: no Api call.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderAgenda, settle } from "../../../../test-support/park/agendaHarness";
import { click, q, qa } from "../../../../test-support/park/componentsHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import type { Api } from "../../api/index";
import { NotBuilt } from "../../api/liveApi";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const text = (root: ParentNode) => (root as HTMLElement).textContent ?? "";
const byText = (root: ParentNode, sel: string, t: string): HTMLElement => {
  const el = qa<HTMLElement>(root, sel).find((e) => (e.textContent ?? "").trim() === t);
  if (!el) throw new Error(`no ${sel} with text "${t}"`);
  return el;
};
const week = (root: ParentNode) => q(root, '[aria-label="This week"]');
const slots = (root: ParentNode) => qa<HTMLElement>(week(root), "[data-slot]");

/** The fixture Api whose every call after `arm()` is recorded by name. */
function recording(over: Partial<Api> = {}) {
  const calls: string[] = [];
  let armed = false;
  const base = { ...createFixtureApi(), ...over } as Api;
  const api = new Proxy(base, {
    get(target, key: string) {
      const v = Reflect.get(target, key);
      if (typeof v !== "function") return v;
      return (...args: unknown[]) => {
        if (armed) calls.push(key);
        return (v as (...a: unknown[]) => unknown)(...args);
      };
    },
  });
  return {
    api,
    calls,
    arm: () => {
      armed = true;
    },
  };
}

describe("FR_UX_15 Find a time: the free slots are named, static ghosts", () => {
  it("FR_UX_15 ghost slots are named buttons, at least 24 px tall, dashed and not animated", async () => {
    const { container } = await renderAgenda();
    click(byText(container, "button", "Find a time"));
    const all = slots(container);
    expect(all).toHaveLength(3);
    for (const s of all) {
      const label = s.getAttribute("data-slot") ?? "";
      expect(s.getAttribute("aria-label"), label).toBe(`Book ${label}, everyone is free`);
      expect(Number.parseFloat(s.style.height), `${label} target height`).toBeGreaterThanOrEqual(
        24,
      );
      // Colour never carries the meaning alone: the slot says "all free" in words and has a plus icon.
      expect(text(s)).toContain("all free");
      expect(s.style.animation ?? "").toBe("");
    }
  });
});

describe("FR_UX_15 booking writes only after a tap, through bookSlot, and never fakes success", () => {
  it("FR_UX_15 finding a time calls no Api; one tap books once with that slot; nothing is fetched", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const bookSlot = vi.fn(() => Promise.resolve({ ok: true as const }));
    const rec = recording({ bookSlot } as unknown as Partial<Api>);
    const { container } = await renderAgenda({ api: rec.api });
    rec.arm();
    click(byText(container, "button", "Find a time"));
    click(byText(week(container), "button", "Cancel"));
    click(byText(container, "button", "Find a time"));
    await settle();
    expect(bookSlot).not.toHaveBeenCalled();
    expect(rec.calls).toEqual([]);
    const second = slots(container)[1] as HTMLElement;
    click(second);
    await settle();
    expect(bookSlot).toHaveBeenCalledTimes(1);
    expect(bookSlot).toHaveBeenCalledWith({ d: 4, s: 9.5, e: 10, l: "Fri 09:30" });
    expect(rec.calls).toEqual(["bookSlot"]);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("FR_UX_15 a refused booking says Not connected yet and adds no event, no pin and no booking", async () => {
    const rec = recording({
      bookSlot: () => Promise.reject(new NotBuilt("bookSlot")),
    } as unknown as Partial<Api>);
    const { container, ...h } = await renderAgenda({ api: rec.api });
    click(byText(container, "button", "Find a time"));
    click(slots(container)[0] as HTMLElement);
    await settle();
    expect(h.toast()).toBe("Not connected yet");
    expect(slots(container)).toHaveLength(3);
    expect(container.querySelector('[data-event="gate"]')).toBeNull();
    expect(container.querySelector('[data-pin="tg"]')).toBeNull();
    expect(container.querySelector('[data-pin="t0"]')).not.toBeNull();
    expect(text(week(container))).not.toContain("booked by Tilo");
    // Nothing was booked, so the person can still look for a time.
    click(byText(week(container), "button", "Cancel"));
    click(byText(container, "button", "Find a time"));
    expect(h.toast()).not.toMatch(/^Already booked/);
    expect(slots(container)).toHaveLength(3);
  });
});

describe("FR_UX_14 Block it is local Park state", () => {
  it("FR_UX_14 Block it makes no Api call and fetches nothing", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const rec = recording();
    const { container } = await renderAgenda({ api: rec.api });
    rec.arm();
    click(byText(q(container, '[data-pin="m0"]'), "button", "Block it"));
    await settle();
    expect(text(q(container, '[data-pin="m0"]'))).toContain("Focus time · Mon 28 Sep");
    expect(rec.calls).toEqual([]);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
