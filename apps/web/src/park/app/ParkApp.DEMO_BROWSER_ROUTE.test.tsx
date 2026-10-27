// @vitest-environment happy-dom
// DEMO-BROWSER: the shell routes /world/:id/browser to the browser page (not to a Park page and not to "Page not found"),
// with the world id from the address; the page itself is covered in pages/World/BrowserPage.DEMO_BROWSER_PAGE.test.tsx.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, q, qa } from "../../../test-support/park/componentsHarness";
import { ParkApp } from "./ParkApp";

vi.mock("../pages/World/BrowserPage", () => ({
  BrowserPage: ({ worldId }: { worldId: string }) => (
    <div data-testid="browser-page-stub">{worldId}</div>
  ),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
};

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
  document.title = "";
});

describe("DEMO_BROWSER_route the shell routes the browser's address", () => {
  it("DEMO_BROWSER_route /world/:id/browser mounts the browser page with the world id", async () => {
    window.history.pushState({}, "", "/world/w%20here/browser");
    const m = mount(<ParkApp />);
    await settle();
    expect(q(m.container, '[data-testid="browser-page-stub"]').textContent).toBe("w here");
    expect(qa(m.container, '[data-testid="park-not-found"]')).toHaveLength(0);
    expect(document.title).toBe("Tilo browser · Tilo");
  });

  it("DEMO_BROWSER_route an address the browser page does not own is not routed to it", async () => {
    window.history.pushState({}, "", "/world/w_here/browser/more");
    const m = mount(<ParkApp />);
    await settle();
    expect(qa(m.container, '[data-testid="browser-page-stub"]')).toHaveLength(0);
    expect(qa(m.container, '[data-testid="park-not-found"]')).toHaveLength(1);
  });
});
