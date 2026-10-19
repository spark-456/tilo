import { describe, expect, it } from "vitest";
import type { Skill } from "../../api/types";
import { skillIconKind } from "./skillIcon";

const skill = (name: string, tools: Skill["tools"] = [], role = ""): Skill =>
  ({ name, tools, role }) as Skill;

describe("CX_UX_SKILL_ICONS skill icon mapping", () => {
  it.each([
    ["Send email", [], "mail"],
    ["Research sources", [], "research"],
    ["Plan meetings", [], "meeting"],
    ["Schedule events", [], "calendar"],
    ["Analyse spreadsheet", [], "table"],
    ["Browse websites", [], "globe"],
    ["Write a brief", [], "writing"],
    ["Review code", [], "code"],
    ["Unclassified", [], "default"],
    ["Unclassified", [["gmail", 1]], "mail"],
  ] as const)("CX_UX_SKILL_ICONS maps %s", (name, tools, expected) => {
    expect(
      skillIconKind(
        skill(
          name,
          tools.map(([tool, level]) => [tool, level] as [string, number]),
        ),
      ),
    ).toBe(expected);
  });

  it("CX_UX_SKILL_ICONS favors a writing name over Gmail and Drive tools", () => {
    expect(
      skillIconKind(
        skill("Draft a supplier brief", [
          ["Google Drive", 1],
          ["Gmail", 2],
        ]),
      ),
    ).toBe("writing");
  });

  it("CX_UX_SKILL_ICONS favors a finance role over Gmail in a multi-tool skill", () => {
    expect(
      skillIconKind(
        skill(
          "Match invoices to purchase orders",
          [
            ["Gmail", 1],
            ["Xero", 2],
            ["Google Sheets", 2],
          ],
          "finance",
        ),
      ),
    ).toBe("table");
  });
});
