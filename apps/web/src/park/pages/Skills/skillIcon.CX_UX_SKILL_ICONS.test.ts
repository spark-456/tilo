import { describe, expect, it } from "vitest";
import type { Skill } from "../../api/types";
import { skillIconKind } from "./skillIcon";

const skill = (name: string, tools: Skill["tools"] = []): Skill => ({ name, tools }) as Skill;

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
});
