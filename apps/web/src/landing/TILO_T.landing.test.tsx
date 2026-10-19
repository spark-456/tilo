// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../test-support/park/componentsHarness";
import { SignInScreen } from "../auth/SignInScreen";
import { RECORDED_RUN } from "./recordedRun";

afterEach(cleanup);

it("TILO_T landing matches design/tilo-t Tilo T Landing artboard", async () => {
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
  expect(headings).toContain("You type one sentence. You get the whole thing back.");
  expect(headings).toContain("Three steps. No jargon, no surprises.");
  expect(headings).toContain("Six helpers. Each one good at one thing.");
  expect(headings).toContain("Your week, and the bits worth keeping.");
  expect(headings).toContain("One town for the whole team.");
  expect(headings.indexOf("One town for the whole team.")).toBeLessThan(
    headings.indexOf("Your week, and the bits worth keeping."),
  );
  expect(headings.indexOf("While you get on with your day.")).toBeLessThan(
    headings.indexOf("Your little city is waiting."),
  );
  const week = document.querySelector("#landing-week")?.closest("section");
  expect(week?.textContent).toContain("Your meetings appear after sign-in");
  expect(week?.querySelector('[role="progressbar"]')).toBeNull();
  expect(document.querySelector(".landing-t-scorecard")).not.toBeNull();
  expect(document.body.textContent).toContain("Brightcell wins, narrowly.");
  expect(document.body.textContent).toContain("Explore a demo town");
});
