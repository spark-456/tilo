// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import type { HttpClient } from "../../api/http";
import { SkillMention } from "./SkillMention";

afterEach(cleanup);

it("FR_SKL_04 catalog picker shows served mine, team and library groups and chooses a served id", async () => {
  const getJson = vi.fn(async () => ({
    skills: [
      {
        id: "m",
        kind: "taught",
        scope: "mine",
        name: "My Plan",
        purpose: "Plan",
        inputs: [],
        tools: [],
        version: 1,
      },
      {
        id: "t",
        kind: "taught",
        scope: "team",
        name: "Team Plan",
        purpose: "Plan together",
        inputs: [],
        tools: [],
        version: 1,
      },
      {
        id: "l",
        kind: "library",
        scope: "library",
        name: "Library Plan",
        purpose: "Plan",
        inputs: [],
        tools: [],
        version: 1,
      },
    ],
  }));
  const chosen = vi.fn();
  const view = mount(
    <div data-park>
      <SkillMention
        text="Write @plan"
        selected={null}
        client={{ getJson } as unknown as HttpClient}
        onChoose={chosen}
        onClear={() => {}}
      />
    </div>,
  );
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(getJson).toHaveBeenCalledWith("/v1/skills/catalog");
  expect(view.container.textContent).toContain("Mine");
  expect(view.container.textContent).toContain("Team");
  expect(view.container.textContent).toContain("Library");
  act(() => {
    (
      Array.from(view.container.querySelectorAll("button")).find((b) =>
        b.textContent?.includes("Team Plan"),
      ) as HTMLButtonElement
    ).click();
  });
  expect(chosen).toHaveBeenCalledWith(expect.objectContaining({ id: "t", scope: "team" }));
});
