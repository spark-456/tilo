// @vitest-environment happy-dom
// TILO-T-WORLD step 6: the Result panel slides in (tSlideR on desktop, tSlideUp as a phone sheet) only when
// artifact.delivered arrives while the page is open; a result already delivered at open just shows.
import { afterEach, expect, it } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { TabPanel } from "./Panels";

afterEach(cleanup);
const panel = (slideWhen: boolean) => (
  <TabPanel
    tab="result"
    on="result"
    title="Result"
    sub="s"
    slideWhen={slideWhen}
    slide="tw-slide-r"
  >
    x
  </TabPanel>
);

it("slides in when delivery arrives while open", () => {
  const m = mount(panel(false));
  expect(m.container.querySelector(".tw-slide-r")).toBeNull();
  m.render(panel(true));
  expect(m.container.querySelector(".tw-slide-r")).not.toBeNull();
});

it("does not slide for a result that was already delivered when the page opened", () => {
  const m = mount(panel(true));
  m.render(panel(true));
  expect(m.container.querySelector(".tw-slide-r")).toBeNull();
});
