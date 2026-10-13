// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount, qa } from "../test-support/park/componentsHarness";

const stage = vi.hoisted(() => vi.fn());
vi.mock("./stage/Stage", () => ({
  Stage: (props: unknown) => {
    stage(props);
    return <div data-testid="recorded-stage" />;
  },
}));
vi.mock("./world/useWorldFixture", () => ({
  useWorldFixture: () => ({
    active: true,
    seq: 7,
    events: [],
    trace: [],
    finished: false,
    status: "paused",
    worldId: "w_recorded",
    selected: "agent",
    layout: null,
    onWorld: stage,
    speedLabel: "Replay at 2× speed",
    loadError: null,
  }),
}));
import { Root } from "./Root";

afterEach(() => {
  cleanup();
  stage.mockClear();
  window.history.pushState({}, "", "/");
});

it.each(["village-basic", "another-recording"])(
  "UI-10 W20 %s recorded stage uses Park navigation and preserves replay state",
  async (fixture) => {
    window.history.pushState({}, "", `/world/w_recorded/stage?fixture=${fixture}`);
    const m = mount(<Root />);
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    await vi.waitFor(() => expect(qa(m.container, "[data-park] nav").length).toBeGreaterThan(0));
    expect(qa(m.container, "main")).toHaveLength(1);
    expect(qa(m.container, 'main [data-testid="recorded-stage"]')).toHaveLength(1);
    expect(m.container.textContent).toContain("Sample recording");
    expect(m.container.textContent).toContain("not your task");
    expect(m.container.textContent).toContain("Replay at 2× speed");
    expect(m.container.textContent).not.toContain("Fixture replay");
    expect(qa(m.container, '[data-testid="replay-scrubber"]')).toHaveLength(1);
    expect(stage).toHaveBeenCalledWith(
      expect.objectContaining({
        seq: 7,
        worldId: "w_recorded",
        selected: "agent",
        paused: true,
        onWorld: stage,
      }),
    );
    expect(document.title).toBe("Sample recording · Tilo");
  },
);
