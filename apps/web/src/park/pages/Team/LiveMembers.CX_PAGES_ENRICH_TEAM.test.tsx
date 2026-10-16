// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { team } from "../../api/fixtures";
import { LiveMembers } from "./LiveMembers";

afterEach(cleanup);

it("CX_PAGES_ENRICH_TEAM_only_shows_columns_with_recorded_values", () => {
  const m = mount(
    <LiveMembers
      team={{
        ...team,
        people: [
          {
            id: "u_a",
            name: "Asha",
            email: null,
            role: null,
            memberships: null,
            dept: null,
            active: null,
            c: null,
          },
        ],
      }}
    />,
  );
  expect([...m.container.querySelectorAll("th")].map((th) => th.textContent)).toEqual(["Person"]);
  expect(m.container.textContent).not.toContain("Not available");
});

it("CX_PAGES_ENRICH_TEAM_empty_directory_guides_an_invite", () => {
  const m = mount(<LiveMembers team={{ ...team, people: [] }} />);
  expect(m.container.textContent).toContain("invite people by email");
});
