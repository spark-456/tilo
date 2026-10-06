// @vitest-environment happy-dom
// WEB-3a: <ParkApp/> with the real registry (every page is still the Placeholder). Pinned surface,
// park/app/ParkApp.tsx: named export `ParkApp` and the same as the default export (Root lazy-imports it).
// The root is `<div data-park data-time>`, the page sits in one <main> inside <Suspense>; an unknown
// /park path shows `data-testid="park-not-found"` (h1 "Page not found", a link to /park/home);
// document.title is "<Page> · Tilo" ("Page not found · Tilo" for the not-found page; the prototype sets no
// title, so this is the default taken); focus moves to the page <h1> (tabindex -1) after a route change.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PAGE_LABEL } from "../../../test-support/park/appHarness";
import { cleanup, mount, q, qa } from "../../../test-support/park/componentsHarness";
import { PAGE_IDS } from "./AppCtx";
import DefaultParkApp, { ParkApp } from "./ParkApp";

// WEB-3b: ParkApp now draws the city backdrop. The real scene takes about 300 ms to build in happy-dom, so
// these WEB-3a tests use the same fast stand-in as the shell tests (test-support/park/shellEngine.ts).
vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

const visit = async (path: string) => {
  window.history.pushState({}, "", path);
  const m = mount(<ParkApp />);
  await settle();
  return m;
};
const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
};
const navigateTo = async (path: string) => {
  await act(async () => {
    window.history.pushState({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await settle();
};

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
  document.title = "";
});

describe("WEB_3a_parkapp: the shell around a page", () => {
  it("WEB_3a_parkapp_default_export_is_ParkApp", () => {
    expect(DefaultParkApp).toBe(ParkApp);
  });

  it("WEB_3a_parkapp_root_is_one_data_park_element_in_day_time", async () => {
    const m = await visit("/park/home");
    const roots = qa(m.container, "[data-park]");
    expect(roots).toHaveLength(1);
    expect(roots[0]?.getAttribute("data-time")).toBe("day");
  });

  it("WEB_3a_parkapp_the_page_sits_in_the_single_main_landmark", async () => {
    const m = await visit("/park/home");
    const mains = qa(m.container, "main");
    expect(mains).toHaveLength(1);
    expect(mains[0]?.querySelector('[data-testid="park-page-home"]')).not.toBeNull();
    expect(mains[0]?.closest("[data-park]")).not.toBeNull();
  });

  it("WEB_3a_parkapp_the_placeholder_says_Not_built_yet_under_one_h1", async () => {
    const m = await visit("/park/home");
    expect(qa(m.container, "h1")).toHaveLength(1);
    expect(q(m.container, "h1").textContent).toBe("Home");
    expect(m.container.textContent).toContain("Not built yet");
  });

  it("WEB_3a_parkapp_the_shell_is_there_while_the_page_chunk_loads", () => {
    window.history.pushState({}, "", "/park/ledger");
    const m = mount(<ParkApp />);
    expect(qa(m.container, "[data-park]")).toHaveLength(1); // Suspense fallback, not a blank root
  });
});

describe("WEB_3a_parkapp: each route renders its page", () => {
  it("WEB_3a_parkapp_each_route_renders_its_page_title_and_one_main", async () => {
    const table = [
      ["/park", "home"],
      ["/park/", "home"],
      ["/park/home", "home"],
      ["/park/worlds", "worlds"],
      ["/park/world/k1", "world"],
      ["/park/skills", "skills"],
      ["/park/skills?id=sk2", "skills"],
      ["/park/ledger", "ledger"],
      ["/park/agenda", "agenda"],
      ["/park/team", "team"],
      ["/park/team?focus=share", "team"],
      ["/park/profile", "profile"],
      ["/park/profile?tab=notifications", "profile"],
      ["/park/connectors", "connectors"],
      ["/park/home?x=1", "home"],
    ] as const;
    for (const [path, id] of table) {
      const m = await visit(path);
      expect(qa(m.container, `[data-testid="park-page-${id}"]`), path).toHaveLength(1);
      expect(q(m.container, "h1").textContent, path).toBe(PAGE_LABEL[id]);
      expect(qa(m.container, "main"), path).toHaveLength(1);
      expect(qa(m.container, '[data-testid^="park-page-"]'), path).toHaveLength(1);
      expect(document.title, path).toBe(`${PAGE_LABEL[id]} · Tilo`);
      m.unmount();
    }
  });

  it("WEB_3a_parkapp_all_nine_pages_are_reachable", async () => {
    const reached: string[] = [];
    for (const id of PAGE_IDS) {
      const m = await visit(id === "world" ? "/park/world/k1" : `/park/${id}`);
      if (m.container.querySelector(`[data-testid="park-page-${id}"]`)) reached.push(id);
      cleanup();
    }
    expect(reached).toEqual([...PAGE_IDS]);
  });
});

describe("WEB_3a_parkapp: a path that is not a page", () => {
  it("WEB_3a_parkapp_not_found_for_unknown_extra_and_malformed_paths", async () => {
    for (const path of ["/park/nope", "/park/home/extra", "/park/world", "/park/world/%E0%A4%A"]) {
      const m = await visit(path);
      expect(qa(m.container, '[data-testid="park-not-found"]'), path).toHaveLength(1);
      expect(qa(m.container, '[data-testid^="park-page-"]'), path).toHaveLength(0);
      expect(qa(m.container, "[data-park]"), path).toHaveLength(1);
      m.unmount();
    }
  });

  it("WEB_3a_parkapp_not_found_has_a_heading_one_main_and_a_title", async () => {
    const m = await visit("/park/nope");
    expect(q(m.container, "h1").textContent).toBe("Page not found");
    expect(qa(m.container, "main")).toHaveLength(1);
    expect(document.title).toBe("Page not found · Tilo");
  });

  it("WEB_3a_parkapp_not_found_links_back_to_park_home", async () => {
    const m = await visit("/park/nope");
    const link = q<HTMLAnchorElement>(m.container, '[data-testid="park-not-found"] a');
    expect(link.getAttribute("href")).toBe("/park/home");
    expect(link.textContent?.trim().length).toBeGreaterThan(0);
  });

  it("WEB_3a_parkapp_clicking_the_not_found_link_goes_home_without_a_page_load", async () => {
    const m = await visit("/park/nope");
    const link = q<HTMLAnchorElement>(m.container, '[data-testid="park-not-found"] a');
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    await act(async () => {
      link.dispatchEvent(ev);
    });
    await settle();
    expect(ev.defaultPrevented).toBe(true);
    expect(window.location.pathname).toBe("/park/home");
    expect(m.container.querySelector('[data-testid="park-page-home"]')).not.toBeNull();
    expect(m.container.querySelector('[data-testid="park-not-found"]')).toBeNull();
  });
});

describe("WEB_3a_parkapp: the browser's history drives the page", () => {
  it("WEB_3a_parkapp_popstate_switches_page_title_and_back_again", async () => {
    const m = await visit("/park/home");
    await navigateTo("/park/ledger");
    expect(m.container.querySelector('[data-testid="park-page-ledger"]')).not.toBeNull();
    expect(m.container.querySelector('[data-testid="park-page-home"]')).toBeNull();
    expect(document.title).toBe("Ledger · Tilo");
    await navigateTo("/park/home");
    expect(m.container.querySelector('[data-testid="park-page-home"]')).not.toBeNull();
    expect(document.title).toBe("Home · Tilo");
  });

  it("WEB_3a_parkapp_a_page_to_not_found_and_back", async () => {
    const m = await visit("/park/home");
    await navigateTo("/park/zzz");
    expect(m.container.querySelector('[data-testid="park-not-found"]')).not.toBeNull();
    await navigateTo("/park/agenda");
    expect(m.container.querySelector('[data-testid="park-page-agenda"]')).not.toBeNull();
  });

  it("WEB_3a_parkapp_focus_moves_to_the_new_pages_h1_after_a_route_change", async () => {
    const m = await visit("/park/home");
    await navigateTo("/park/team");
    const h1 = q(m.container, "h1");
    expect(h1.textContent).toBe("Team");
    expect(h1.getAttribute("tabindex")).toBe("-1");
    expect(document.activeElement).toBe(h1);
  });

  it("WEB_3a_parkapp_focus_moves_to_the_not_found_heading_too", async () => {
    const m = await visit("/park/home");
    await navigateTo("/park/missing");
    expect(document.activeElement).toBe(q(m.container, "h1"));
  });
});
