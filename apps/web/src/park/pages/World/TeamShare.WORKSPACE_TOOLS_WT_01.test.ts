import { expect, it } from "vitest";
import { CONSENT } from "./TeamShare";

it("WORKSPACE_TOOLS_WT_01 warns that later sharing reveals output based on private reads", () => {
  expect(CONSENT).toContain("past and future");
  expect(CONSENT).toContain("may include results based on mail, calendar and Drive reads");
});
