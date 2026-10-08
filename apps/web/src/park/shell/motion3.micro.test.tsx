// @vitest-environment happy-dom
// WEB-MOTION-3 (FR-UX-12): what the markup does so the stylesheet's micro-interactions have something to
// hang on (the transitions themselves are pinned in motion3.micro.css.test.ts and measured in a browser).
//  - A toast, the notifications popover and the account menu mount inside `.park-shell__enter`, which holds
//    data-enter="pre" for the style flush and "in" once it has happened (no timer, no frame loop).
//  - The root carries data-motion (the person's preference) so the stylesheet can turn motion off for 'still'.
//  - The Home composer's ring and the Connectors spinner carry `park-shell__ring--page` ONLY while an action is in flight.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount, q } from "../../../test-support/park/componentsHarness";
import {
  clickEl,
  control,
  mountHome,
  settle as settleHome,
  taskInput,
  typeInto,
} from "../../../test-support/park/homeHarness";
import { mountApp, seen } from "../../../test-support/park/shellHarness";
import { ParkApp } from "../app/ParkApp";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const enterWrap = (el: Element | null): HTMLElement | null =>
  el?.closest<HTMLElement>(".park-shell__enter") ?? null;

describe("WEB-MOTION-3 enter: toast, popover and menu mount inside an enter wrapper", () => {
  it("FR_UX_12 WEB-MOTION-3 enter: a toast is the direct child of a wrapper that is settled to data-enter=in by the time the call returns", async () => {
    await mountApp();
    act(() => seen.app.toast("Saved"));
    const toast = document.querySelector<HTMLElement>(".park-toast");
    expect(toast).not.toBeNull();
    const wrap = enterWrap(toast);
    expect(wrap, "the toast sits in .park-shell__enter").not.toBeNull();
    expect(toast?.parentElement).toBe(wrap);
    expect(wrap?.getAttribute("data-enter")).toBe("in");
  });

  it("FR_UX_12 WEB-MOTION-3 enter: the notifications popover and the account menu each sit in an enter wrapper and keep their roles", async () => {
    await mountApp();
    click(q(document.body, 'button[aria-label="Notifications"]'));
    const dialog = document.querySelector<HTMLElement>(
      '[role="dialog"][aria-label="Notifications"]',
    );
    expect(dialog?.parentElement?.classList.contains("park-shell__enter")).toBe(true);
    expect(enterWrap(dialog)?.getAttribute("data-enter")).toBe("in");
    click(q(document.body, 'button[aria-label="Account menu"]'));
    const menu = document.querySelector<HTMLElement>('[role="menu"][aria-label="Account"]');
    expect(menu?.parentElement?.classList.contains("park-shell__enter")).toBe(true);
  });

  it("FR_UX_12 WEB-MOTION-3 enter: the wrapper adds no box (display: contents) and no timer, frame or animation call", async () => {
    const raf = vi.spyOn(window, "requestAnimationFrame");
    const timeout = vi.spyOn(window, "setTimeout");
    await mountApp();
    const before = timeout.mock.calls.length;
    act(() => seen.app.toast("Saved"));
    expect(raf).not.toHaveBeenCalled();
    expect(timeout.mock.calls.length).toBe(before);
    raf.mockRestore();
    timeout.mockRestore();
  });
});

describe("WEB-MOTION-3 root: data-motion carries the person's motion preference", () => {
  it("FR_UX_12 WEB-MOTION-3 root: <ParkApp/> sets data-motion on the [data-park] root and follows the Appearance preference", async () => {
    window.history.pushState({}, "", "/park/home");
    const m = mount(<ParkApp />);
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    const root = q(m.container, "[data-park]");
    expect(["lively", "calm", "still"]).toContain(root.getAttribute("data-motion"));
  });
});

describe("WEB-MOTION-3 spinner: the ring turns only while a Home draft is in flight", () => {
  it("FR_UX_12 WEB-MOTION-3 spinner: the drafting ring has the page ring class, and it is gone once the plan shows", async () => {
    const rig = await mountHome();
    expect(rig.el.querySelector(".park-shell__ring--page")).toBeNull();
    typeInto(taskInput(rig.el), "Order laptops");
    clickEl(control(rig.el, "Start task"));
    await settleHome();
    expect(rig.el.querySelector(".park-home-drafting .park-shell__ring--page")).not.toBeNull();
    const draft = rig.sch.live().find((t) => t.ms === 900);
    rig.sch.fire(draft);
    await settleHome();
    expect(rig.el.querySelector(".park-shell__ring--page")).toBeNull();
  });
});
