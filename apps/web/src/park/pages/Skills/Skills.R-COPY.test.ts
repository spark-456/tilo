import { expect, it } from "vitest";
import { unavailableStepCopy } from "./TeachWizard";

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

it("R-COPY keeps other unavailable steps specific", () => {
  expect(unavailableStepCopy({ text: "Buy the item", reason: "unavailable_action" })).toBe(
    "Buy the item · unavailable_action",
  );
});
