import { describe, expect, it } from "vitest";
import { catalogOf, mentionQuery, sendWithSkill } from "./skillRoute";

describe("FR-SKL-04 skill mention picker", () => {
  it("FR_SKL_04 only opens for a trailing @ query and keeps catalog groups from the server", () => {
    expect(mentionQuery("Write with @plan")).toBe("plan");
    expect(mentionQuery("Write @plan now")).toBeNull();
    expect(mentionQuery("email@example.com")).toBeNull();
    expect(
      catalogOf({
        skills: [
          {
            id: "my_plan",
            kind: "taught",
            scope: "mine",
            name: "My Plan",
            purpose: "Write a plan",
            inputs: [],
            tools: [],
            version: 1,
          },
          {
            id: "lib_report",
            kind: "library",
            scope: "library",
            name: "Report",
            purpose: "Write a report",
            inputs: [],
            tools: [],
            version: "1.0",
          },
          {
            id: "unsafe",
            kind: "taught",
            scope: "team",
            name: "Bad",
            purpose: 4,
            inputs: [],
            tools: [],
            version: 1,
          },
        ],
      }),
    ).toEqual([
      expect.objectContaining({ id: "my_plan", scope: "mine" }),
      expect.objectContaining({ id: "lib_report", scope: "library" }),
    ]);
  });

  it("FR_SKL_04 never submits an unbound selected skill as if it were pinned", () => {
    const send = (text: string) => text;
    expect(sendWithSkill("Write a plan", null, send)).toBe("Write a plan");
    expect(sendWithSkill("Write a plan", "my_plan", send)).toBeNull();
  });
});
