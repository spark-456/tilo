// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../test-support/park/componentsHarness";
import { SignInScreen } from "../auth/SignInScreen";
import { RECORDED_RUN } from "./recordedRun";

afterEach(cleanup);

it("CX-T-LANDING keeps the Studio story and adds honest T agenda and task ideas", async () => {
  mount(
    <SignInScreen
      busy={false}
      failed={false}
      failedText="Failed."
      onGoogle={() => undefined}
      onDemo={() => undefined}
    />,
  );
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  const headings = [...document.querySelectorAll("h2")].map((heading) => heading.textContent);
  expect(headings).toContain("Your week, and the bits worth keeping.");
  expect(headings).toContain("A good place to start.");
  expect(headings.indexOf("Everything in play, at a glance.")).toBeLessThan(
    headings.indexOf("Your week, and the bits worth keeping."),
  );
  expect(headings.indexOf("A good place to start.")).toBeLessThan(
    headings.indexOf("Your little city is waiting."),
  );
  const week = document.querySelector("#landing-week")?.closest("section");
  expect(week?.textContent).toContain("Your meetings appear after sign-in");
  expect(week?.textContent).not.toMatch(/\d+ of \d+ credits|follow-ups drafted|meeting at \d/i);
  expect(week?.querySelector('[role="progressbar"]')).toBeNull();
  const replay = document.querySelector('[aria-label="Recorded example events"]');
  expect(replay?.textContent).toContain(RECORDED_RUN.facts.planned);
  expect(replay?.textContent).toContain(RECORDED_RUN.facts.done);
  expect(replay?.textContent).toContain("Recorded example");
});
