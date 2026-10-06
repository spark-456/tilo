// @vitest-environment happy-dom
import type { Layout } from "@tilo/contracts";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { villageBasicEvents, villageBasicLayout } from "../../test-support/worldFixtures";
import { reduce } from "../world/reducer";
import { WorldThumb } from "./WorldThumb";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const layout = villageBasicLayout() as unknown as Layout;
const events = villageBasicEvents();

async function html(node: React.ReactElement): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.append(container);
  await act(async () => {
    createRoot(container).render(node);
  });
  return container;
}

describe("UX-227 S-14 thumbnail: agents stand where the run has put them (HR-1)", () => {
  it("draws no agent before any event, and the spawned ones once the run has recorded them", async () => {
    const none = await html(<WorldThumb layout={layout} state={reduce(layout, [])} />);
    expect(none.querySelectorAll('[data-testid="thumb-agent"]')).toHaveLength(0);

    const state = reduce(layout, events as never);
    const spawned = Object.values(state.agents).filter((a) => a.spawned && a.location).length;
    expect(spawned).toBeGreaterThan(0);
    const some = await html(<WorldThumb layout={layout} state={state} />);
    const figures = some.querySelectorAll('[data-testid="thumb-agent"]');
    expect(figures).toHaveLength(spawned);
    // A rank shows by shape, so every figure carries its rank for the test and the eye.
    for (const f of figures) expect(f.getAttribute("data-rank")).toBeTruthy();
  });
});
