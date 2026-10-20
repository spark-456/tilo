import { expect, it } from "vitest";
import { NO_HOST_COPY, unavailableStepCopy } from "./TeachWizard";

const COPY =
  "YouTube isn't connected, and liking or commenting posts publicly as you. Tilo can watch and summarise a video, or draft a comment for you to post.";

it("R-COPY explains the YouTube limitation and offers useful alternatives", () => {
  expect(
    unavailableStepCopy({
      text: "Like or comment on YouTube videos",
      reason: "not_declared",
    }),
  ).toBe(COPY);
});

it("DEMO_BROWSER a browse step with no site says to name one, never that the browser is coming", () => {
  const copy = unavailableStepCopy({ text: "Open the supplier page", reason: "no_host" });
  expect(copy).toBe(`Open the supplier page · ${NO_HOST_COPY}`);
  expect(
    unavailableStepCopy({ text: "Open youtube.com in a tab", reason: "not_allowed" }),
  ).not.toContain("coming");
});

it("R-COPY keeps other unavailable steps specific", () => {
  expect(unavailableStepCopy({ text: "Buy the item", reason: "unavailable_action" })).toBe(
    "Buy the item · unavailable_action",
  );
});
