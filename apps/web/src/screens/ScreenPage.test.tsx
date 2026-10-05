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

const tick = () => act(async () => new Promise((resolve) => setTimeout(resolve, 0)));

describe("FR_WLD_11 #361 ScreenPage", () => {
  it("follows a screen root swapped after mount", async () => {
    const heights = { scroll: 800, client: 800 };
    const main = page(heights);
    expect(main.hasAttribute("tabindex")).toBe(false);
    heights.scroll = 1200; // the new content is taller; only the swap tells the page
    main.append(document.createElement("div"));
    await tick();
    expect(main.getAttribute("tabindex")).toBe("0");
  });

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
