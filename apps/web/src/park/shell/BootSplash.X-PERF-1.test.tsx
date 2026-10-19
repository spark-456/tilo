// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { BootSplash } from "./BootSplash";

// The Park console guard (d141e731) fails on React's act() warning, so the test declares its act environment.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const eager = vi.hoisted(() => vi.fn());
vi.mock("./prefetch", () => ({ prefetchPages: eager }));
vi.mock("../app/context", () => ({ useSchedule: () => vi.fn() }));
vi.mock("./motion", () => ({ useMotionOff: () => true }));

it("X-PERF-1 finishing Home boot does not fetch unused page chunks", async () => {
  const host = document.createElement("div");
  const root = createRoot(host);
  try {
    await act(async () => root.render(<BootSplash ready={false} />));
    await act(async () => root.render(<BootSplash ready />));
    expect(eager).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
  }
});
