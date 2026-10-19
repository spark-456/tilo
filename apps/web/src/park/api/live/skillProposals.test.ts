import { expect, it } from "vitest";
import { proposalsFromList } from "./skillProposals";

const proposal = {
  id: "p1",
  skill_id: "writing",
  domain: "delivery",
  status: "proposed",
  from_version: "1.0.0",
  to_version: "1.0.1",
  diff: "-old\n+new",
  provenance: { world_id: "w1", proposed_by: "lead", proposed_at: "2026-10-11T00:00:00Z" },
};
it("FR_AGT_15 maps the expert diff without inventing reviewer permissions", () => {
  expect(proposalsFromList({ proposals: [proposal] }, "w1")).toEqual([proposal]);
  expect(proposalsFromList({ proposals: [] }, "w1")).toEqual([]);
});
it("FR_AGT_15 refuses unreadable and cross-world proposals", () => {
  for (const body of [
    null,
    {},
    { proposals: [{}] },
    { proposals: [{ ...proposal, diff: null }] },
    { proposals: [{ ...proposal, status: "unknown" }] },
  ])
    expect(proposalsFromList(body, "w1")).toBeNull();
  expect(proposalsFromList({ proposals: [proposal] }, "other")).toBeNull();
});
