// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { Waiting } from "./TopBar";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function html(node: React.ReactElement): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.append(container);
  await act(async () => {
    createRoot(container).render(node);
  });
  return container;
}

describe("UX-227-C1 the Needs-you chip is a link, except on the queue's own page", () => {
  it("renders a link elsewhere and plain text with aria-current on the queue", async () => {
    const link = await html(<Waiting count={2} here={false} to="/needs-you" />);
    expect(link.querySelector("a")?.getAttribute("href")).toBe("/needs-you");
    const text = await html(<Waiting count={2} here to="/needs-you" />);
    expect(text.querySelector("a")).toBeNull();
    expect(text.querySelector('[aria-current="page"]')?.textContent).toContain("2");
  });
});
