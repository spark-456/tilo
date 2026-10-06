// @vitest-environment happy-dom
// WEB-3b: <AppShell/> composes the shell (README Architecture: CityBackdrop, TopNav, popovers, page outlet,
// Toast, WorldLoader, BootSplash) and ParkApp (WEB-3a) renders it around the page. Pinned surface:
//   park/shell/AppShell.tsx: `AppShell({ children: ReactNode })`; reads useApp(), useParkStore() and
//     useParkApi(); imports "./park.shell.css". It renders NO `[data-park]` root (ParkApp keeps it) and
//     exactly one `main.park-shell__main` holding `children`; on every page except home the children sit
//     inside `div.park-shell__column` (max-width 1320, margin 0 auto, padding 100px 24px 56px). On mount it
//     reads the notifications and the user through useParkApi(), so a fixture Api shows "Sample data" at
//     once. The toast is the Toast component fed by the store (role status, Undo). BootSplash gets
//     `ready` (the engines are built) and is gone by the first settled render.
//   ParkApp keeps its WEB-3a surface: one `[data-park][data-time]` root, one <main>, the page inside it.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi } from "../../../test-support/park/appHarness";
import { cleanup, click, mount, q, qa } from "../../../test-support/park/componentsHarness";
import { liveApi, mountShell, seen, settle } from "../../../test-support/park/shellHarness";
import { sceneSpy } from "../../../test-support/park/shellEngine";
import { ParkApp } from "../app/ParkApp";
import { AppShell } from "./AppShell";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  vi.useRealTimers();
  cleanup();
  window.history.pushState({}, "", "/");
  sceneSpy.mockClear();
});

const kid = <div data-testid="kid">page</div>;
const status = () => qa(document.body, '[role="status"]');
const waitDone = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await settle();
};

describe("WEB_3b_shell: the pieces", () => {
  it("WEB_3b_shell_renders_the_nav_the_backdrop_and_one_main_around_the_children", async () => {
    const { m } = mountShell(<AppShell>{kid}</AppShell>, { path: "/park/ledger" });
    await settle();
    expect(qa(m.container, "header.park-nav")).toHaveLength(1);
    expect(qa(m.container, "nav[aria-label]")).toHaveLength(1);
    expect(qa(m.container, '[data-testid="park-backdrop"]')).toHaveLength(1);
    expect(q(m.container, '[data-testid="park-backdrop"]').getAttribute("aria-hidden")).toBe("true");
    const mains = qa(m.container, "main");
    expect(mains).toHaveLength(1);
    expect(mains[0]?.classList.contains("park-shell__main")).toBe(true);
    expect(mains[0]?.contains(q(m.container, '[data-testid="kid"]'))).toBe(true);
    expect(q(m.container, "header.park-nav").contains(q(m.container, '[data-testid="kid"]'))).toBe(false);
  });

  it("WEB_3b_shell_inner_pages_sit_in_the_1320_column_and_home_does_not", async () => {
    for (const [path, column] of [
      ["/park/home", 0],
      ["/park/worlds", 1],
      ["/park/world/k1", 1],
      ["/park/ledger", 1],
      ["/park/profile", 1],
    ] as const) {
      const { m } = mountShell(<AppShell>{kid}</AppShell>, { path });
      await settle();
      const cols = qa(m.container, "main .park-shell__column");
      expect(cols, path).toHaveLength(column);
      if (column) expect(cols[0]?.contains(q(m.container, '[data-testid="kid"]')), path).toBe(true);
      m.unmount();
    }
  });

  it("WEB_3b_shell_renders_no_data_park_root_of_its_own", async () => {
    const { m } = mountShell(<AppShell>{kid}</AppShell>);
    await settle();
    expect(qa(m.container, "[data-park]")).toHaveLength(1); // the harness root only
  });

  it("WEB_3b_shell_the_boot_splash_is_gone_once_the_engines_are_built", async () => {
    const { m } = mountShell(<AppShell>{kid}</AppShell>);
    await settle();
    expect(document.body.querySelector(".park-boot")).toBeNull();
    expect(m.container.querySelector('[aria-label="Loading Tilo"]')).toBeNull();
  });

  it("WEB_3b_shell_builds_the_city_once", async () => {
    mountShell(<AppShell>{kid}</AppShell>);
    await settle();
    act(() => seen.app.decide("depot"));
    expect(sceneSpy).toHaveBeenCalledTimes(1);
  });
});

describe("WEB_3b_shell: toast, popovers and the loader inside the shell", () => {
  it("WEB_3b_shell_no_toast_until_something_toasts_then_the_Toast_with_Undo", async () => {
    mountShell(<AppShell>{kid}</AppShell>);
    await settle();
    expect(status()).toHaveLength(0);
    act(() => seen.app.decide("depot"));
    expect(status()).toHaveLength(1);
    expect(status()[0]?.textContent).toContain("Approved £3,420 for Laptop Depot");
    expect(status()[0]?.classList.contains("park-toast")).toBe(true);
    click(q(status()[0] as HTMLElement, "button"));
    expect(seen.app.dec.depot).toBe(false);
    expect(status()).toHaveLength(0);
  });

  it("WEB_3b_shell_the_toast_hides_when_its_4200_ms_timer_fires", async () => {
    const { sch } = mountShell(<AppShell>{kid}</AppShell>);
    await settle();
    act(() => seen.app.toast("Saved"));
    expect(sch.live().map((t) => t.ms)).toEqual([4200]);
    act(() => sch.fire(sch.live()[0]));
    expect(status()).toHaveLength(0);
  });

  it("WEB_3b_shell_the_bell_lists_the_five_notifications_the_shell_fetched", async () => {
    mountShell(<AppShell>{kid}</AppShell>);
    await settle();
    click(q(document.body, 'button[aria-label="Notifications"]'));
    expect(qa(document.body, "button.park-notif__row")).toHaveLength(5);
  });

  it("WEB_3b_shell_the_avatar_opens_the_account_menu_with_the_fetched_user", async () => {
    mountShell(<AppShell>{kid}</AppShell>);
    await settle();
    click(q(document.body, 'button[aria-label="Account menu"]'));
    expect(q(document.body, ".park-acct__name").textContent).toBe("Alex Morgan");
    expect(qa(document.body, '[role="dialog"][aria-label="Notifications"]')).toHaveLength(0);
  });

  it("WEB_3b_shell_the_shell_reads_notifications_and_the_user_through_the_Api", async () => {
    const api = fakeApi();
    const notes = vi.spyOn(api, "getNotifications");
    const who = vi.spyOn(api, "getUser");
    mountShell(<AppShell>{kid}</AppShell>, { api });
    await settle();
    expect(notes).toHaveBeenCalled();
    expect(who).toHaveBeenCalled();
  });

  it("WEB_3b_shell_a_fixture_Api_shows_the_Sample_data_chip_without_any_page_fetching", async () => {
    const { m } = mountShell(<AppShell>{kid}</AppShell>);
    await settle();
    expect(seen.store.getState().sources.fixture).toBe(true);
    expect(q(m.container, "button.park-nav__chip").textContent).toBe("Sample data");
  });

  it("WEB_3b_shell_a_live_only_Api_shows_no_chip", async () => {
    const { m } = mountShell(<AppShell>{kid}</AppShell>, { api: liveApi() });
    await settle();
    expect(seen.store.getState().sources).toEqual({ fixture: false, live: true });
    expect(m.container.querySelector("button.park-nav__chip")).toBeNull();
  });

  it("WEB_3b_shell_a_notification_row_runs_the_loader_then_navigates_at_step_3", async () => {
    const { navigate, sch } = mountShell(<AppShell>{kid}</AppShell>);
    await settle();
    click(q(document.body, 'button[aria-label="Notifications"]'));
    const row = qa<HTMLButtonElement>(document.body, "button.park-notif__row").find((r) =>
      r.textContent?.includes("Competitor pricing is ready"),
    ) as HTMLButtonElement;
    click(row);
    expect(qa(document.body, '[data-testid="world-loader"]')).toHaveLength(1);
    expect(q(document.body, ".park-wl__name").textContent).toBe("Competitor pricing");
    expect(qa(document.body, '[role="dialog"]')).toHaveLength(0); // the menu closed
    expect(navigate).not.toHaveBeenCalled();
    for (let i = 0; i < 3; i++) act(() => sch.fire(sch.live()[0]));
    expect(navigate).toHaveBeenCalledWith("/park/world/comp");
    expect(qa(document.body, '[data-testid="world-loader"]')).toHaveLength(1);
    act(() => sch.fire(sch.live()[0]));
    expect(qa(document.body, '[data-testid="world-loader"]')).toHaveLength(0);
  });
});

describe("WEB_3b_parkapp: the real ParkApp wears the shell", () => {
  const visit = async (path: string) => {
    window.history.pushState({}, "", path);
    const m = mount(<ParkApp />);
    await waitDone();
    return m;
  };

  it("WEB_3b_parkapp_one_root_with_the_nav_the_backdrop_and_a_single_main", async () => {
    const m = await visit("/park/home");
    const roots = qa(m.container, "[data-park]");
    expect(roots).toHaveLength(1);
    expect(qa(roots[0] as HTMLElement, "nav[aria-label]")).toHaveLength(1);
    expect(qa(roots[0] as HTMLElement, '[data-testid="park-backdrop"][aria-hidden="true"]')).toHaveLength(1);
    expect(qa(m.container, "main")).toHaveLength(1);
    expect(q(m.container, "main").querySelector('[data-testid="park-page-home"]')).not.toBeNull();
    expect(qa(m.container, "h1")).toHaveLength(1);
  });

  it("WEB_3b_parkapp_a_tab_click_changes_the_page_and_the_current_tab_without_a_load", async () => {
    const m = await visit("/park/home");
    const ledger = qa<HTMLAnchorElement>(m.container, "nav a.park-nav__tab").find((a) =>
      a.textContent?.startsWith("Ledger"),
    ) as HTMLAnchorElement;
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    await act(async () => {
      ledger.dispatchEvent(ev);
    });
    await waitDone();
    expect(ev.defaultPrevented).toBe(true);
    expect(window.location.pathname).toBe("/park/ledger");
    expect(m.container.querySelector('[data-testid="park-page-ledger"]')).not.toBeNull();
    expect(
      qa(m.container, 'nav a[aria-current="page"]').map((a) => a.textContent),
    ).toEqual(["Ledger"]);
    expect(qa(m.container, "main .park-shell__column")).toHaveLength(1);
  });

  it("WEB_3b_parkapp_the_Worlds_badge_shows_2", async () => {
    const m = await visit("/park/home");
    expect(q(m.container, ".park-nav__badge").textContent).toBe("2");
  });

  it("WEB_3b_parkapp_the_day_night_button_flips_data_time_on_the_one_root", async () => {
    const m = await visit("/park/home");
    const btn = q<HTMLButtonElement>(m.container, 'button[aria-label="Switch to night"]');
    click(btn);
    expect(q(m.container, "[data-park]").getAttribute("data-time")).toBe("night");
    expect(sceneSpy).toHaveBeenLastCalledWith(expect.objectContaining({ night: true }));
    click(q(m.container, 'button[aria-label="Switch to day"]'));
    expect(q(m.container, "[data-park]").getAttribute("data-time")).toBe("day");
  });

  it("WEB_3b_parkapp_the_sample_chip_shows_on_the_default_fixture_api", async () => {
    const m = await visit("/park/home");
    expect(q(m.container, "button.park-nav__chip").textContent).toBe("Sample data");
  });

  it("WEB_3b_parkapp_a_world_from_the_bell_loads_for_3x250_ms_then_the_page_swaps_and_the_card_goes", async () => {
    const m = await visit("/park/home");
    vi.useFakeTimers();
    click(q(m.container, 'button[aria-label="Notifications"]'));
    const row = qa<HTMLButtonElement>(m.container, "button.park-notif__row").find((r) =>
      r.textContent?.includes("Competitor pricing is ready"),
    ) as HTMLButtonElement;
    click(row);
    expect(m.container.querySelector('[data-testid="world-loader"]')).not.toBeNull();
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
    expect(window.location.pathname).toBe("/park/world/comp");
    expect(m.container.querySelector('[data-testid="world-loader"]')).not.toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(250);
    });
    expect(m.container.querySelector('[data-testid="world-loader"]')).toBeNull();
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    expect(m.container.querySelector('[data-testid="park-page-world"]')).not.toBeNull();
  });

  it("WEB_3b_parkapp_a_deep_link_to_not_found_still_has_the_shell_and_one_main", async () => {
    const m = await visit("/park/nope");
    expect(qa(m.container, "nav[aria-label]")).toHaveLength(1);
    expect(qa(m.container, "main")).toHaveLength(1);
    expect(q(m.container, "main").querySelector('[data-testid="park-not-found"]')).not.toBeNull();
  });
});
