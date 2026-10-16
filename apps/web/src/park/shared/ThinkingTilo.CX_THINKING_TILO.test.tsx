// @vitest-environment happy-dom
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { ThinkingTilo } from "./ThinkingTilo";

it("CX_THINKING_TILO_renders_saved_motion_and_an_accessible_status", () => {
  const html = renderToStaticMarkup(createElement(ThinkingTilo, { label: "Syncing calendar" }));
  expect(html).toContain('aria-label="Syncing calendar"');
  expect(html).toContain('media="(prefers-reduced-motion: reduce)"');
  expect(html).toMatch(/\/loader\/thinking-.*\.webp/);
  expect(html).not.toContain("park-shell__ring");
});
