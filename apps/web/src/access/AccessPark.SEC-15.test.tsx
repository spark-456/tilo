// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, mount, q } from "../../test-support/park/componentsHarness";
import { SignUpDeclaration } from "./SignUpDeclaration";
import { UnderConstruction } from "./UnderConstruction";

afterEach(cleanup);

it("SEC-15 Park declaration offers descriptive cards and keeps Continue waiting while busy", () => {
  const submit = vi.fn();
  mount(<SignUpDeclaration busy onSubmit={submit} />);
  expect(q(document.body, "h1")?.textContent).toBe("One quick question");
  expect(document.body.textContent).toContain("Runs use recorded replay models");
  expect(document.body.textContent).toContain("It cannot be changed from this page");
  expect(document.querySelectorAll("label.park-access__choice")).toHaveLength(2);
  click(q(document.body, 'input[value="judge"]'));
  const button = q<HTMLButtonElement>(document.body, 'button[type="submit"]');
  expect(button.disabled).toBe(true);
  click(button);
  expect(submit).not.toHaveBeenCalled();
});

it.each(["declaration", "notice"])(
  "SEC-15 Park %s has a day/night city and a scoped glass card",
  (page) => {
    mount(
      page === "declaration" ? <SignUpDeclaration onSubmit={() => {}} /> : <UnderConstruction />,
    );
    const screen = q<HTMLElement>(document.body, "[data-park].park-access");
    expect(screen).not.toBeNull();
    expect(screen.dataset.time).toBe("day");
    expect(q(screen, ".park-access__card")).not.toBeNull();
    click(q(screen, 'button[aria-label="Switch to the night city"]'));
    expect(screen.dataset.time).toBe("night");
    click(q(screen, 'button[aria-label="Switch to the day city"]'));
    expect(screen.dataset.time).toBe("day");
  },
);
