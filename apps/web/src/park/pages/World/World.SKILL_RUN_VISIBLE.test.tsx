// SKILL-RUN-VISIBLE: run events show the served skill's human name in the World header and Story.
// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import {
  liveWorldsApi,
  mountWorld,
  settle,
  textOf,
} from "../../../../test-support/park/worldHarness";
import { HttpClient } from "../../../api/http";
import type { Skill } from "../../api/types";
import type { RunEvent } from "./useRunEvents";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const skill: Skill = {
  id: "exec_summary",
  name: "Executive summary",
  team: "",
  owner: "",
  role: "",
  runs: null,
  rate: null,
  last: "",
  improved: "",
  status: "live",
  st: "trusted",
  from: "library",
  tools: [],
  used: [],
  steps: [],
};

describe("SKILL_RUN_VISIBLE", () => {
  it("SKILL_RUN_VISIBLE_world_header_and_story_use_the_skill_name_from_the_recorded_load", async () => {
    const api = liveWorldsApi();
    api.getSkills = vi.fn(async () => ({ data: [skill], source: "live" as const }));
    const client = new HttpClient({
      baseUrl: "http://localhost:0",
      fetch: async () => new Response("{}", { status: 404 }),
    });
    let publish: ((event: RunEvent) => void) | undefined;
    client.subscribeEvents = (_world, onEvent) => {
      publish = onEvent as (event: RunEvent) => void;
      return () => undefined;
    };
    const rig = await mountWorld({ id: "k1", api, client });
    const event: RunEvent = {
      seq: 1,
      type: "skill.loaded",
      ts: "2026-10-17T09:00:00.000Z",
      credits: 0,
      summary: "The Specialist loaded the skill exec_summary, version 1.0.0.",
      data: { skill: "exec_summary", version: "1.0.0" },
    };
    await act(async () => publish?.(event));
    await settle();

    const header = rig.el.querySelector(".park-world-titles");
    const story = rig.el.querySelector('[role="tabpanel"][data-tab="story"]');
    expect.soft(textOf(header ?? rig.el)).toContain("Uses skill: Executive summary");
    expect.soft(textOf(story ?? rig.el)).toContain("loaded the skill Executive summary");
    expect.soft(textOf(story ?? rig.el)).not.toContain("exec_summary");
  });
});
