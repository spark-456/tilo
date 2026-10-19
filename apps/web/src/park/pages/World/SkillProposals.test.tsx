// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { fakeScheduler } from "../../../../test-support/park/appHarness";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { appFor } from "../../../../test-support/park/worldHarness";
import { HttpClient } from "../../../api/http";
import { createFixtureApi } from "../../api/fixtureApi";
import { ParkProvider } from "../../app/context";
import { SkillProposals } from "./SkillProposals";
import { WorldPage } from "./WorldPage";

afterEach(cleanup);
it("FR_AGT_15 W3 sample world has no proposals, errors or live requests", async () => {
  const fetch = vi.fn(async () => new Response('{"detail":"Not Found"}', { status: 404 }));
  let panel: ReturnType<typeof mount> | undefined;
  await act(async () => {
    panel = mount(
      <SkillProposals
        client={new HttpClient({ baseUrl: "https://api.test", fetch })}
        worldId="w_sample_village_basic"
      />,
    );
  });
  if (!panel) throw new Error("Panel did not mount");
  expect(fetch).not.toHaveBeenCalled();
  expect(panel.container.textContent).toContain("No skill proposals yet.");
  expect(panel.container.querySelector('[role="alert"]')).toBeNull();
  expect(panel.container.querySelectorAll("button")).toHaveLength(0);
});

it("FR_AGT_15 W3 a world sharing the sample prefix still requests its live proposals", async () => {
  const fetch = vi.fn(async (_url: RequestInfo | URL) => new Response('{"proposals":[]}'));
  await act(async () => {
    mount(
      <SkillProposals
        client={new HttpClient({ baseUrl: "https://api.test", fetch })}
        worldId="w_sample_village_basic_real"
      />,
    );
  });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0]?.[0]).toBe(
    "https://api.test/worlds/w_sample_village_basic_real/skill-proposals",
  );
});
it("FR_AGT_15 the live World page reaches proposals and the demo World never requests them", async () => {
  for (const source of ["live", "fixture"] as const) {
    const api = createFixtureApi();
    const result = await api.getWorlds({}, []);
    const world = result.data[0];
    if (!world) throw new Error("Test world missing");
    api.getWorlds = async () => ({ data: result.data, source });
    const fetch = vi.fn(
      async (_url: RequestInfo | URL) => new Response(JSON.stringify({ proposals: [] })),
    );
    const sch = fakeScheduler();
    await act(async () => {
      mount(
        <ParkProvider
          api={api}
          worldClient={new HttpClient({ baseUrl: "https://api.test", fetch })}
          schedule={sch.schedule}
        >
          <WorldPage app={appFor(world.id)} />
        </ParkProvider>,
      );
    });
    // A live page also reads the world's events (its sharing line, BQ-CTX-TEAMWORLD TSW-5b, and the run progress
    // poll, UI-10 B8); proposals are the one request this test is about. A demo World requests nothing.
    const urls = fetch.mock.calls.map((c) => String(c[0]));
    const base = `https://api.test/worlds/${encodeURIComponent(world.id)}`;
    expect(urls.filter((u) => u.endsWith("/skill-proposals"))).toEqual(
      source === "live" ? [`${base}/skill-proposals`] : [],
    );
    const others = urls.filter((u) => !u.endsWith("/skill-proposals"));
    expect(others.every((u) => u === `${base}/events`)).toBe(true);
    expect(others.length > 0).toBe(source === "live");
    cleanup();
  }
});
const p = {
  id: "p /1",
  skill_id: "writing",
  domain: "delivery",
  status: "proposed",
  from_version: "1.0.0",
  to_version: "1.0.1",
  diff: "-old\n+new",
  provenance: { world_id: "w1", proposed_by: "lead", proposed_at: "2026-10-11T00:00:00Z" },
};
it("FR_AGT_15 World panel reads and accepts or declines through the existing route", async () => {
  for (const verb of ["approve", "reject"] as const) {
    const fetch = vi.fn(
      async (_url: RequestInfo | URL, init?: RequestInit) =>
        new Response(
          JSON.stringify(
            init?.method === "POST"
              ? { proposal: { ...p, status: verb === "approve" ? "approved" : "rejected" } }
              : { proposals: [p] },
          ),
        ),
    );
    const client = new HttpClient({ baseUrl: "https://api.test", fetch });
    let root: ReturnType<typeof mount> | undefined;
    await act(async () => {
      root = mount(<SkillProposals client={client} worldId="w1" />);
    });
    if (!root) throw new Error("Panel did not mount");
    expect(root.container.textContent).toContain("-old\n+new");
    const button = [...root.container.querySelectorAll("button")].find(
      (b) => b.textContent === (verb === "approve" ? "Accept" : "Decline"),
    );
    await act(async () => {
      if (!button) throw new Error("Review button missing");
      button.click();
    });
    expect(fetch.mock.calls.map((c) => c[0])).toEqual([
      "https://api.test/worlds/w1/skill-proposals",
      `https://api.test/worlds/w1/skill-proposals/p%20%2F1/${verb}`,
    ]);
    expect(JSON.parse(String(fetch.mock.calls[1]?.[1]?.body))).toEqual({});
    expect(root.container.textContent).toContain(verb === "approve" ? "approved" : "rejected");
    expect(root.container.querySelector("button")).toBeNull();
    root.unmount();
  }
});
it("FR_AGT_15 forbidden reads and writes stay honest and never announce success", async () => {
  let rejectWrite = false;
  const fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(rejectWrite ? { error: "not_expert" } : { proposals: [p] }), {
        status: rejectWrite ? 403 : 200,
      }),
  );
  let root: ReturnType<typeof mount> | undefined;
  await act(async () => {
    root = mount(
      <SkillProposals
        client={new HttpClient({ baseUrl: "https://api.test", fetch })}
        worldId="w1"
      />,
    );
  });
  if (!root) throw new Error("Panel did not mount");
  rejectWrite = true;
  await act(async () => {
    const button = root?.container.querySelector("button");
    if (!button) throw new Error("Review button missing");
    button.click();
  });
  expect(root.container.querySelector('[role="alert"]')).not.toBeNull();
  expect(root.container.textContent).not.toContain("approved");
});
