// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";
import { cleanup, click, mount, q } from "../../../test-support/park/componentsHarness";
import { FirstRunBanner } from "./FirstRunBanner";

afterEach(() => {
  cleanup();
  localStorage.clear();
});
it("FIRST_RUN_HR_1_banner_dismissal_is_per_person_and_page_and_survives_remount", () => {
  const props = { page: "home", person: "person-a", first: true };
  const node = mount(<FirstRunBanner {...props} />);
  expect(node.container.textContent).toContain("You are looking at sample data.");
  click(q(node.container, "button"));
  expect(node.container.textContent).toBe("");
  node.render(<FirstRunBanner {...props} page="agenda" />);
  expect(node.container.textContent).toContain("Sample");
  node.render(<FirstRunBanner {...props} person="person-b" />);
  expect(node.container.textContent).toContain("Sample");
  node.unmount();
  const next = mount(<FirstRunBanner {...props} />);
  expect(next.container.textContent).toBe("");
});
it("FIRST_RUN_HR_1_banner_hides_immediately_when_the_first_real_run_starts", () => {
  const node = mount(<FirstRunBanner page="ledger" person="person-a" first />);
  expect(node.container.querySelector("aside")).not.toBeNull();
  node.render(<FirstRunBanner page="ledger" person="person-a" first={false} />);
  expect(node.container.textContent).toBe("");
});
