// @vitest-environment happy-dom
import { act, createElement } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, expect, it } from "vitest";
import { TeamResources } from "./TeamResources";

let resourceRoot: Root | null = null;
afterEach(() => {
  if (resourceRoot) act(() => resourceRoot?.unmount());
  resourceRoot = null;
});
const emptyPinboards = async () => ({
  data: { rows: [], truncated: false },
  source: "live" as const,
});

it("FR_TEAM_01_team_resources_show_shared_worlds_and_server_returned_team_pins_only", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  resourceRoot = createRoot(host);
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
  await act(async () => {
    resourceRoot?.render(
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
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(host.textContent).toContain("Q3 deck");
  expect(host.textContent).toContain("Launch notes");
  expect(host.textContent).not.toContain("Private note");
});

it("FR_TEAM_01_team_resources_use_shared_empty_states_when_lists_are_empty", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  resourceRoot = createRoot(host);
  await act(async () => {
    resourceRoot?.render(
      createElement(TeamResources, {
        worlds: [],
        worldsState: "ready",
        readPinboards: emptyPinboards,
      }),
    );
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(host.textContent).toContain("No shared worlds yet");
  expect(host.textContent).toContain("No team pins yet");
});
