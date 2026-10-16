// @vitest-environment happy-dom
import { createElement } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { TeamResources } from "./TeamResources";
import { settle } from "./testApp";

afterEach(cleanup);
const emptyPinboards = async () => ({
  data: { rows: [], truncated: false },
  source: "live" as const,
});

it("FR_TEAM_01_team_resources_show_shared_worlds_and_server_returned_team_pins_only", async () => {
  const readPinboards = async () => ({
    data: {
      rows: [
        {
          id: "pb_team",
          title: "Launch notes",
          status: "active",
          at: "2026-10-16",
          body: null,
          scope: "Team tm_abc",
          setter: null,
          personalUser: null,
          source: null,
          end: null,
        },
        {
          id: "pb_personal",
          title: "Private note",
          status: "active",
          at: "2026-10-16",
          body: null,
          scope: "Personal",
          setter: null,
          personalUser: "u1",
          source: null,
          end: null,
        },
      ],
      truncated: false,
    },
    source: "live" as const,
  });
  const mounted = mount(
    createElement(TeamResources, {
      worlds: [
        {
          id: "w_shared",
          name: "Q3 deck",
          short: "Q3 deck",
          tier: "Village",
          tool: "",
          st: "running",
          agents: 0,
          spend: "",
          spendV: 0,
          nextL: "",
          nextV: "",
          owner: "",
          started: "",
          access: "team",
        },
      ],
      worldsState: "ready",
      readPinboards,
    }),
  );
  await settle();
  expect(mounted.container.textContent).toContain("Q3 deck");
  expect(mounted.container.textContent).toContain("Launch notes");
  expect(mounted.container.textContent).not.toContain("Private note");
});

it("FR_TEAM_01_team_resources_use_shared_empty_states_when_lists_are_empty", async () => {
  const mounted = mount(
    createElement(TeamResources, {
      worlds: [],
      worldsState: "ready",
      readPinboards: emptyPinboards,
    }),
  );
  await settle();
  expect(mounted.container.textContent).toContain("No shared worlds yet");
  expect(mounted.container.textContent).toContain("No team pins yet");
});
