// @vitest-environment happy-dom
// #361 (FR-WLD-11): the routed page is a scroll container, so it is keyboard-reachable and named while its
// content overflows (axe scrollable-region-focusable), and plain (no tab stop) while everything fits.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { ScreenPage } from "./ScreenPage";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: ReturnType<typeof createRoot> | null = null;
afterEach(() => {
  act(() => root?.unmount());
  document.body.innerHTML = "";
  root = null;
});

function page(heights: { scroll: number; client: number }): HTMLElement {
  const proto = HTMLElement.prototype;
  Object.defineProperty(proto, "scrollHeight", { configurable: true, get: () => heights.scroll });
  Object.defineProperty(proto, "clientHeight", { configurable: true, get: () => heights.client });
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => root?.render(<ScreenPage screenId="S_23">text</ScreenPage>));
  return host.querySelector("main") as HTMLElement;
}

describe("FR_WLD_11 #361 ScreenPage", () => {
  it("takes a tab stop and a name while its content overflows", () => {
    const main = page({ scroll: 1200, client: 800 });
    expect(main.getAttribute("tabindex")).toBe("0");
    expect(main.getAttribute("aria-label")).toBe("Page content");
  });

  it("has neither while everything fits", () => {
    const main = page({ scroll: 800, client: 800 });
    expect(main.hasAttribute("tabindex")).toBe(false);
    expect(main.hasAttribute("aria-label")).toBe(false);
  });
});
