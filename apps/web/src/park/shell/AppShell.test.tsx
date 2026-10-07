// @vitest-environment happy-dom
// WEB-3b: <AppShell/> composes the shell (README Architecture: CityBackdrop, TopNav, popovers, page outlet,
// Toast, WorldLoader, BootSplash) and ParkApp (WEB-3a) renders it around the page. Pinned surface:
//   park/shell/AppShell.tsx: named export `AppShell({ children: ReactNode })`. It reads the app, the store and
//   the Api from ParkProvider; renders no `[data-park]` root of its own (ParkApp keeps the one root) and
//   exactly one <main> holding `children`; reads the notifications and the user through useParkApi() on mount,
//   so a fixture Api shows "Sample data" with no page asking for data.
// The WEB-3a ParkApp tests (ParkApp.test.tsx, ParkApp.app.test.tsx) stay as they are; the tests here add the
// shell's expectations only. They mock the scene engine for speed (see shellEngine.ts).
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi } from "../../../test-support/park/appHarness";
import { cleanup, click, mount, q, qa } from "../../../test-support/park/componentsHarness";
import {
  liveApi,
  mountApp,
  mountShell,
  seen,
  settle,
} from "../../../test-support/park/shellHarness";
import { ParkApp } from "../app/ParkApp";
import { AppShell } from "./AppShell";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  vi.useRealTimers();
  cleanup();
  window.history.pushState({}, "", "/");
});

const status = () => qa(document.body, '[role="status"]');
/** The browser's own "the fade has finished" (WEB-MOTION-2: the card and the splash fade out, then go). */
const animationEnd = (el: Element | null | undefined) =>
  act(() => {
    el?.dispatchEvent(new Event("animationend", { bubbles: true }));
  });
const waitDone = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await settle();
};

describe("WEB_3b_shell: the pieces and where they sit", () => {
  it("WEB_3b_shell_the_nav_the_backdrop_and_one_main_that_holds_the_page", async () => {
    const { m } = await mountApp({ path: "/park/ledger" });
    expect(qa(m.container, "header nav[aria-label]")).toHaveLength(1);
    expect(qa(m.container, '[aria-hidden="true"] [data-testid="fake-scene"]')).toHaveLength(1);
    const mains = qa(m.container, "main");
    expect(mains).toHaveLength(1);
    expect(mains[0]?.contains(q(m.container, '[data-testid="kid"]'))).toBe(true);
    expect(q(m.container, "header").contains(q(m.container, '[data-testid="kid"]'))).toBe(false);
  });

  it("WEB_3b_shell_home_and_the_inner_pages_both_hold_the_page_in_main", async () => {
    for (const path of ["/park/home", "/park/worlds", "/park/world/k1", "/park/profile"]) {
      const { m } = await mountApp({ path });
      expect(q(m.container, "main").contains(q(m.container, '[data-testid="kid"]')), path).toBe(
        true,
      );
      m.unmount();
    }
  });

  it("WEB_3b_shell_the_boot_splash_is_gone_once_the_shell_has_mounted", async () => {
    await mountApp();
    // Updated for WEB-MOTION-2: the splash fades over .45 s once ready (no longer a loading status), then goes.
    expect(document.querySelector('[role="status"][aria-label="Loading Tilo"]')).toBeNull();
    animationEnd(document.querySelector('[aria-label="Loading Tilo"]'));
    expect(document.querySelector('[aria-label="Loading Tilo"]')).toBeNull();
  });

  it("WEB_3b_shell_the_shell_reads_notifications_and_the_user_through_the_Api", async () => {
    const api = fakeApi();
    const notes = vi.spyOn(api, "getNotifications");
    const who = vi.spyOn(api, "getUser");
    mountShell(
      <AppShell>
        <div />
      </AppShell>,
      { api },
    );
    await settle();
    expect(notes).toHaveBeenCalled();
    expect(who).toHaveBeenCalled();
  });

  it("WEB_3b_shell_a_live_Api_is_read_the_same_way_and_is_not_marked_as_sample", async () => {
    await mountApp({ api: liveApi() });
    expect(seen.store.getState().sources).toEqual({ fixture: false, live: true });
  });
});

describe("WEB_3b_shell: the toast", () => {
  it("WEB_3b_shell_no_toast_until_something_toasts_then_one_with_Undo", async () => {
    await mountApp();
    expect(status()).toHaveLength(0);
    act(() => seen.app.decide("depot"));
    expect(status()).toHaveLength(1);
    expect(status()[0]?.textContent).toContain("Approved £3,420 for Laptop Depot");
    expect(status()[0]?.getAttribute("aria-live")).toBe("polite");
    expect(status()[0]?.closest("[data-park]")).not.toBeNull();
    click(q(status()[0] as HTMLElement, "button"));
    expect(seen.app.dec.depot).toBe(false);
    expect(status()).toHaveLength(0);
  });

  it("WEB_3b_shell_the_toast_hides_when_its_4200_ms_timer_fires", async () => {
    const { sch } = await mountApp();
    act(() => seen.app.toast("Saved"));
    expect(sch.live().map((t) => t.ms)).toEqual([4200]);
    act(() => sch.fire(sch.live()[0]));
    expect(status()).toHaveLength(0);
  });
});

describe("WEB_3b_shell: the popovers and the loader work together", () => {
  it("WEB_3b_shell_a_notification_row_opens_the_world_through_the_loader_then_the_page", async () => {
    const { navigate, sch } = await mountApp();
    click(q(document.body, 'button[aria-label="Notifications"]'));
    const row = qa<HTMLButtonElement>(document.body, '[role="dialog"] button').find((r) =>
      (r.textContent ?? "").includes("Competitor pricing is ready"),
    ) as HTMLButtonElement;
    click(row);
    const card = () => status().find((e) => (e.textContent ?? "").includes("OPENING"));
    expect(card()?.textContent).toContain("Competitor pricing");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(navigate).not.toHaveBeenCalled();
    for (let i = 0; i < 3; i++) act(() => sch.fire(sch.live()[0]));
    expect(navigate).toHaveBeenCalledWith("/world/comp");
    expect(card()).toBeDefined();
    act(() => sch.fire(sch.live()[0]));
    // Updated for WEB-MOTION-2: the card fades out over 280 ms after the last step, and goes at animationend.
    expect(card()).toBeDefined();
    animationEnd(card());
    expect(card()).toBeUndefined();
  });
});

describe("WEB_3b_parkapp: the real ParkApp wears the shell", () => {
  const visit = async (path: string) => {
    window.history.pushState({}, "", path);
    const m = mount(<ParkApp />);
    await waitDone();
    return m;
  };

  it("WEB_3b_parkapp_one_root_with_the_nav_the_backdrop_and_a_single_main_holding_the_page", async () => {
    const m = await visit("/park/home");
    const roots = qa(m.container, "[data-park]");
    expect(roots).toHaveLength(1);
    expect(qa(roots[0] as HTMLElement, "header nav[aria-label]")).toHaveLength(1);
    expect(
      qa(roots[0] as HTMLElement, '[aria-hidden="true"] [data-testid="fake-scene"]'),
    ).toHaveLength(1);
    expect(qa(m.container, "main")).toHaveLength(1);
    expect(q(m.container, "main").querySelector('[data-testid="park-page-home"]')).not.toBeNull();
    expect(qa(m.container, "h1")).toHaveLength(1);
  });

  it("WEB_3b_parkapp_a_tab_click_changes_the_page_and_the_current_tab_without_a_load", async () => {
    const m = await visit("/park/home");
    const ledger = qa<HTMLAnchorElement>(m.container, "header nav a").find((a) =>
      (a.textContent ?? "").startsWith("Ledger"),
    ) as HTMLAnchorElement;
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    await act(async () => {
      ledger.dispatchEvent(ev);
    });
    // Updated for WEB-MOTION-2: a tab click fades the old page out (200 ms) and swaps after it.
    await act(async () => {
      await new Promise((done) => setTimeout(done, 400));
    });
    await waitDone();
    expect(ev.defaultPrevented).toBe(true);
    expect(window.location.pathname).toBe("/ledger");
    expect(m.container.querySelector('[data-testid="park-page-ledger"]')).not.toBeNull();
    expect(qa(m.container, 'header nav a[aria-current="page"]').map((a) => a.textContent)).toEqual([
      "Ledger",
    ]);
  });

  it("WEB_3b_parkapp_the_Worlds_badge_reads_2", async () => {
    const m = await visit("/park/home");
    const worlds = qa(m.container, "header nav a").find((a) =>
      (a.textContent ?? "").startsWith("Worlds"),
    );
    expect(worlds?.textContent).toBe("Worlds2");
  });

  it("WEB_3b_parkapp_the_day_night_button_flips_data_time_on_the_one_root", async () => {
    const m = await visit("/park/home");
    click(q(m.container, 'button[aria-label="Switch to night"]'));
    expect(q(m.container, "[data-park]").getAttribute("data-time")).toBe("night");
    click(q(m.container, 'button[aria-label="Switch to day"]'));
    expect(q(m.container, "[data-park]").getAttribute("data-time")).toBe("day");
  });

  it("WEB_3b_parkapp_the_sample_data_chip_shows_on_the_default_fixture_Api", async () => {
    const m = await visit("/park/home");
    const chip = qa<HTMLButtonElement>(m.container, "header button").find(
      (b) => b.textContent === "Sample data",
    );
    expect(chip).toBeDefined();
  });

  it("WEB_3b_parkapp_a_world_from_the_bell_loads_for_3x250_ms_then_the_page_swaps_and_the_card_goes", async () => {
    const m = await visit("/park/home");
    vi.useFakeTimers();
    click(q(m.container, 'button[aria-label="Notifications"]'));
    const row = qa<HTMLButtonElement>(m.container, '[role="dialog"] button').find((r) =>
      (r.textContent ?? "").includes("Competitor pricing is ready"),
    ) as HTMLButtonElement;
    click(row);
    const card = () =>
      qa(m.container, '[role="status"]').find((e) => (e.textContent ?? "").includes("OPENING"));
    expect(card()).toBeDefined();
    expect(window.location.pathname).toBe("/park/home");
    await act(async () => {
      vi.advanceTimersByTime(249);
    });
    expect(window.location.pathname).toBe("/park/home");
    await act(async () => {
      vi.advanceTimersByTime(1 + 250 * 2);
    });
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    expect(window.location.pathname).toBe("/world/comp");
    expect(card()).toBeDefined();
    await act(async () => {
      vi.advanceTimersByTime(250);
    });
    // Updated for WEB-MOTION-2: the card fades out over 280 ms after the last step, and goes at animationend.
    expect(card()).toBeDefined();
    animationEnd(card());
    expect(card()).toBeUndefined();
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    expect(m.container.querySelector('[data-testid="park-page-world"]')).not.toBeNull();
  });

  it("WEB_3b_parkapp_the_not_found_page_still_has_the_shell_and_one_main", async () => {
    const m = await visit("/park/nope");
    expect(qa(m.container, "header nav[aria-label]")).toHaveLength(1);
    expect(qa(m.container, "main")).toHaveLength(1);
    expect(q(m.container, "main").querySelector('[data-testid="park-not-found"]')).not.toBeNull();
  });
});
