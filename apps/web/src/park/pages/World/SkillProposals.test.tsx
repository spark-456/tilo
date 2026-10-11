// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { HttpClient } from "../../../api/http";
import { SkillProposals } from "./SkillProposals";

afterEach(cleanup);
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
