// @vitest-environment happy-dom
// WEB-CUTOVER: <ParkApp/> at the root paths. The registry is replaced by one probe page per id (as in
// ParkApp.app.test.tsx). Pinned: the route comes from the root path or the /park alias; app.go() pushes
// ROOT paths; the nav tabs, the logo and the Park NotFound "Go to Home" link carry root hrefs; the document
// title behaviour is unchanged.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount, q, qa } from "../../../test-support/park/componentsHarness";
import type { AppCtx } from "./AppCtx";
import { ParkApp } from "./ParkApp";

const held = vi.hoisted(() => ({ app: undefined as AppCtx | undefined }));

vi.mock("./pages", async () => {
  const { lazy, createElement } = await import("react");
  const make = (id: string) =>
    lazy(() =>
      Promise.resolve({
        default: ({ app }: { app: AppCtx }) => {
          held.app = app;
          return createElement(
            "div",
            { "data-testid": `probe-${id}` },
            createElement("h1", { tabIndex: -1 }, `Probe ${id}`),
          );
        },
      }),
    );
  const ids = [
    "home",
    "worlds",
    "world",
    "skills",
    "ledger",
    "agenda",
    "team",
    "profile",
    "connectors",
  ];
  return { PAGES: Object.fromEntries(ids.map((id) => [id, make(id)])) };
});

const app = (): AppCtx => {
  if (!held.app) throw new Error("no page rendered yet");
  return held.app;
};
const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
};
const visit = async (path: string) => {
  window.history.pushState({}, "", path);
  const m = mount(<ParkApp />);
  await settle();
  return m;
};
const where = () => window.location.pathname + window.location.search;

afterEach(() => {
  vi.useRealTimers();
  cleanup();
  window.history.pushState({}, "", "/");
  held.app = undefined;
  document.title = "";
});

describe("WEB_CUTOVER_parkapp: the route comes from the root path", () => {
  it("WEB_CUTOVER_06_each_root_path_renders_its_page_and_title", async () => {
    const table = [
      ["/", "home", "Home"],
      ["/worlds", "worlds", "Worlds"],
      ["/world/k1", "world", "World"],
      ["/team", "team", "Team"],
      ["/connectors", "connectors", "Connectors"],
      ["/skills", "skills", "Skills"],
      ["/agenda", "agenda", "Agenda"],
      ["/ledger", "ledger", "Ledger"],
      ["/profile", "profile", "Profile"],
      ["/park/home", "home", "Home"],
      ["/park/world/k1", "world", "World"],
    ] as const;
    for (const [path, id, title] of table) {
      const m = await visit(path);
      expect(qa(m.container, `[data-testid="probe-${id}"]`), path).toHaveLength(1);
      expect(qa(m.container, "main"), path).toHaveLength(1);
      expect(document.title, path).toBe(`${title} · Tilo`);
      m.unmount();
    }
  });

  it("WEB_CUTOVER_06_the_page_gets_its_params_from_the_root_path", async () => {
    await visit("/world/k1");
    expect(app()).toMatchObject({ page: "world", params: { id: "k1" } });
    cleanup();
    await visit("/skills?id=sk3&x=1");
    expect(app()).toMatchObject({ page: "skills", params: { id: "sk3" } });
    cleanup();
    await visit("/team?focus=share");
    expect(app()).toMatchObject({ page: "team", params: { focus: "share" } });
  });
});

describe("WEB_CUTOVER_parkapp: navigation writes root paths", () => {
  it("WEB_CUTOVER_06_go_pushes_root_paths", async () => {
    const m = await visit("/ledger");
    await act(async () => app().go("worlds"));
    await settle();
    expect(where()).toBe("/worlds");
    expect(m.container.querySelector('[data-testid="probe-worlds"]')).not.toBeNull();
    await act(async () => app().go("home"));
    await settle();
    expect(where()).toBe("/");
    expect(m.container.querySelector('[data-testid="probe-home"]')).not.toBeNull();
    await act(async () => app().go("skills", { id: "sk2" }));
    await settle();
    expect(where()).toBe("/skills?id=sk2");
    expect(app().params).toEqual({ id: "sk2" });
    await act(async () => app().go("team"));
    await settle();
    expect(where()).toBe("/team");
  });

  it("WEB_CUTOVER_06_go_world_pushes_world_slash_id_after_the_loader", async () => {
    const m = await visit("/");
    vi.useFakeTimers();
    await act(async () => app().go("world", { id: "k1" }));
    expect(where()).toBe("/"); // the loader runs first
    await act(async () => {
      vi.advanceTimersByTime(340 * 3);
    });
    await settle();
    expect(where()).toBe("/world/k1");
    expect(m.container.querySelector('[data-testid="probe-world"]')).not.toBeNull();
    expect(app().params).toEqual({ id: "k1" });
  });

  it("WEB_CUTOVER_06_the_toast_Open_action_goes_to_the_new_world_at_the_root_path", async () => {
    const m = await visit("/");
    await act(async () => {
      app().addWorld("quick", "Order lunch");
    });
    const open = qa<HTMLButtonElement>(m.container, '[role="status"] button');
    expect(open.map((b) => b.textContent)).toEqual(["Open"]);
    click(open[0] as HTMLButtonElement);
    await settle();
    expect(where()).toBe("/world/new1");
  });

  it("WEB_CUTOVER_06_the_nav_tabs_and_the_logo_link_to_root_paths", async () => {
    const m = await visit("/ledger");
    const tabs = qa<HTMLAnchorElement>(q(m.container, "header nav"), "a");
    expect(tabs.map((a) => a.getAttribute("href"))).toEqual([
      "/",
      "/worlds",
      "/skills",
      "/needs", // STUDIO-4
      "/ledger",
      "/agenda",
      "/team",
    ]);
    expect(q(m.container, 'a[aria-label="Tilo home"]').getAttribute("href")).toBe("/");
    for (const a of qa<HTMLAnchorElement>(q(m.container, "header"), "a")) {
      expect(a.getAttribute("href"), a.textContent ?? "").not.toMatch(/^\/park(\/|$)/);
    }
  });

  it("WEB_CUTOVER_06_clicking_a_nav_tab_changes_the_address_to_its_root_path", async () => {
    const m = await visit("/");
    const tab = (name: string) =>
      qa<HTMLAnchorElement>(q(m.container, "header nav"), "a").find((a) =>
        (a.textContent ?? "").startsWith(name),
      ) as HTMLAnchorElement;
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    await act(async () => {
      tab("Ledger").dispatchEvent(ev);
    });
    await settle();
    expect(ev.defaultPrevented).toBe(true);
    expect(where()).toBe("/ledger");
    click(tab("Home"));
    await settle();
    expect(where()).toBe("/");
  });
});

describe("WEB_CUTOVER_parkapp: the Park NotFound page", () => {
  it("M1_NOTFOUND_1_unknown_address_can_search_worlds", async () => {
    const m = await visit("/no-such-page");
    const link = q<HTMLAnchorElement>(
      m.container,
      '[data-testid="park-not-found"] a[href="/worlds"]',
    );
    expect(link.textContent).toBe("Search worlds");
    await act(async () => {
      link.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }));
    });
    await settle();
    expect(where()).toBe("/worlds");
    expect(m.container.querySelector('[data-testid="probe-worlds"]')).not.toBeNull();
  });
  it("WEB_CUTOVER_06_not_found_links_to_the_root_home", async () => {
    const m = await visit("/park/nope");
    const link = q<HTMLAnchorElement>(m.container, '[data-testid="park-not-found"] a');
    expect(link.getAttribute("href")).toBe("/");
    // UI-10 W7 specifies the browser title; the visible heading stays Page not found.
    expect(document.title).toBe("Not found · Tilo");
  });

  it("WEB_CUTOVER_06_clicking_the_not_found_link_goes_to_slash_without_a_page_load", async () => {
    const m = await visit("/park/nope");
    const link = q<HTMLAnchorElement>(m.container, '[data-testid="park-not-found"] a');
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    await act(async () => {
      link.dispatchEvent(ev);
    });
    await settle();
    expect(ev.defaultPrevented).toBe(true);
    expect(where()).toBe("/");
    expect(m.container.querySelector('[data-testid="probe-home"]')).not.toBeNull();
    expect(m.container.querySelector('[data-testid="park-not-found"]')).toBeNull();
  });
});
