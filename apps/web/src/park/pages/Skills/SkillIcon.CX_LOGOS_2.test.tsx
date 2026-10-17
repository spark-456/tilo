// @vitest-environment happy-dom
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, expect, it } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import type { Skill } from "../../api/types";
import { SkillIcon } from "./skillIcon";

afterEach(cleanup);

it("CX_LOGOS_2_loads_a_local_colour_icon_for_a_taught_skill", () => {
  const skill = { name: "Schedule events", role: "", tools: [] } as unknown as Skill;
  const rig = mount(<SkillIcon skill={skill} />);
  const img = rig.container.querySelector("img");
  expect(img?.getAttribute("src")).toBe("/park/skills/calendar.svg");
  expect(img?.getAttribute("loading")).toBe("lazy");
  expect(img?.getAttribute("alt")).toBe("Schedule events icon");
  expect(existsSync(resolve(process.cwd(), "public/park/skills/calendar.svg"))).toBe(true);
});
