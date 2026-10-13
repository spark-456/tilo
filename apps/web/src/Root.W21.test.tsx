// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount, qa } from "../test-support/park/componentsHarness";
import { FIXTURE_WORLD_ID } from "./api/fixtures/derived";

vi.mock("./stage/Stage", () => ({ Stage: () => <div data-testid="kept-stage" /> }));
vi.mock("./screens/FlowShell", () => ({
  FlowShell: () => (
    <section>
      <h1>Task flow</h1>
    </section>
  ),
}));
vi.mock("./screens/routes", () => ({
  matchScreen: (path: string) =>
    /\/stage\/?$|\/start\/?$|\/task\//.test(path)
      ? null
      : {
          id: "W21-screen",
          params: [],
          Component: () => <h1>Kept screen</h1>,
        },
}));
import { Root } from "./Root";

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

it.each(["/screens", "/screens/cards", "/dev/components"])(
  "UI-10 W21 unreachable development route %s keeps its existing shell",
  async (path) => {
    window.history.pushState({}, "", path);
    const rig = mount(<Root />);
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    expect(qa(rig.container, "[data-park]")).toHaveLength(0);
    expect(qa(rig.container, '[data-testid="left-rail"]')).toHaveLength(1);
  },
);

it.each([
  "/start",
  "/task/t1/understanding",
  "/task/t1/approaches",
  ...["stage", "story", "trace", "delivery", "inspect/B1"].map(
    (lens) => `/world/${FIXTURE_WORLD_ID}/${lens}`,
  ),
  "/needs-you/gate",
  "/needs-you/consent",
  "/meeting",
  "/library",
  "/library/artifacts",
  "/autonomy",
  "/channels",
  "/mail",
  "/connections",
  "/estimate",
  "/pilot",
  "/meetings",
  "/meetings/m1",
  "/plate",
  "/pinboards",
  "/calendar",
  "/more",
  "/worlds/replays",
  "/team/console",
])("UI-10 W21 %s retains its content inside Park chrome", async (path) => {
  window.history.pushState({}, "", path);
  const rig = mount(<Root />);
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await vi.waitFor(() => expect(qa(rig.container, "[data-park] nav").length).toBeGreaterThan(0));
  expect(qa(rig.container, "main")).toHaveLength(1);
  expect(rig.container.textContent).toMatch(/Task flow|Kept screen/);
  expect(rig.container.textContent).not.toContain("Fixture replay");
  expect(rig.container.textContent).toContain("Sample");
  expect(qa(rig.container, '[data-testid="left-rail"], [data-testid="bottom-tabs"]')).toHaveLength(
    0,
  );
});
