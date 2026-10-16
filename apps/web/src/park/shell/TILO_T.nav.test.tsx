// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi } from "../../../test-support/park/appHarness";
import { cleanup, click, q, qa } from "../../../test-support/park/componentsHarness";
import { mountApp, seen } from "../../../test-support/park/shellHarness";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

describe("CX-T-NAV phone navigation", () => {
  it("CX-T-NAV includes Connectors in the desktop T board nav without losing Ledger", async () => {
    const { m } = await mountApp({
      api: fakeApi(),
      viewport: { vw: 1440, vh: 900 },
      path: "/connectors",
    });
    const links = qa<HTMLAnchorElement>(m.container, "header nav a");
    expect(links.map((link) => link.textContent?.trim().replace(/\d+$/, ""))).toEqual([
      "Home", "Chat", "Worlds", "Needs you", "Agenda", "Skills", "Team", "Connectors", "Ledger",
    ]);
    expect(links[7]?.getAttribute("aria-current")).toBe("page");
  });

  it("CX-T-NAV shows five 44px phone tabs with the live Needs count and route state", async () => {
    const { m, navigate } = await mountApp({
      api: fakeApi(),
      viewport: { vw: 390, vh: 844 },
      path: "/needs",
    });
    const nav = q<HTMLElement>(m.container, 'nav[aria-label="Phone tabs"]');
    const links = qa<HTMLAnchorElement>(nav, "a");
    expect(qa<SVGElement>(nav, "svg").map((svg) => svg.getAttribute("viewBox"))).toEqual([
      "0 0 24 24", "0 0 24 24", "0 0 24 24", "0 0 24 24", "0 0 24 24",
    ]);
    expect(links.map((link) => link.textContent?.trim())).toEqual([
      "Home",
      "Worlds",
      "Chat",
      "Needs you2",
    ]);
    expect(links[3]?.getAttribute("aria-current")).toBe("page");
    expect(qa<HTMLButtonElement>(nav, "button").map((button) => button.textContent?.trim())).toEqual([
      "More",
    ]);

    await act(async () => seen.app.decide("depot"));
    expect(links[3]?.textContent?.trim()).toBe("Needs you1");
    await act(async () => click(links[0] as Element));
    expect(navigate).toHaveBeenLastCalledWith("/");
  });

  it("CX-T-NAV More reaches secondary pages and is current on Connectors", async () => {
    const { m, navigate } = await mountApp({
      api: fakeApi(),
      viewport: { vw: 390, vh: 844 },
      path: "/connectors",
    });
    const more = q<HTMLButtonElement>(m.container, 'nav[aria-label="Phone tabs"] button');
    expect(more.getAttribute("aria-current")).toBe("page");
    await act(async () => click(more));
    const menu = q(document.body, '[role="menu"][aria-label="More pages"]');
    const connectors = qa<HTMLElement>(menu, '[role="menuitem"]').find((item) =>
      item.textContent?.startsWith("Connectors"),
    );
    expect(connectors).toBeDefined();
    await act(async () => click(connectors as Element));
    expect(navigate).toHaveBeenLastCalledWith("/connectors");
  });
});
