// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount, qa } from "../../test-support/park/componentsHarness";
import { Stage } from "./Stage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("UI-10 W21 embedded stage preserves its named keyboard region within one main", () => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  const rig = mount(
    <main>
      <Stage {...{ embedded: true }} />
    </main>,
  );
  expect(qa(rig.container, "main")).toHaveLength(1);
  const frame = rig.container.querySelector('[data-testid="stage-frame"]');
  expect(frame?.tagName).toBe("SECTION");
  expect(frame?.getAttribute("aria-label")).toBe("World stage");
  expect(frame?.getAttribute("tabindex")).toBe("0");
});

it("UI-10 W21 standalone stage retains its main landmark", () => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  const rig = mount(<Stage />);
  expect(qa(rig.container, 'main[aria-label="World stage"]')).toHaveLength(1);
});
