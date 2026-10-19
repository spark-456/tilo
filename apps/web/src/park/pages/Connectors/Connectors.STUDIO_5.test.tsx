// @vitest-environment happy-dom
// UI-STUDIO-5 Connectors (design/studio-v2 "Tilo S Connectors"): the apps beside "What Tilo may do". Each app's
// level is one radio choice in plain words (Always, Ask me, Read only, Never) saved as the server's own level (act,
// draft, read, off) with one write by an Owner; anyone else reads it. The live list shows each app's state as the
// server sent it, and nothing more.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { flush, makeApp, renderPage } from "../../../../test-support/park/connectorsDom";
import type { Api } from "../../api";
import type { TeamOp, TeamView } from "../../api/live/teamLive";
import { createLiveApi } from "../../api/liveApi";

afterEach(cleanup);

const view = (role = "Owner"): TeamView => ({
  version: 1,
  me: { id: "u1", role },
  members: [{ id: "u1", role, limit_minor: null }],
  switches: [],
  tools: [{ connector: "gmail", level: "act" }],
  capabilities: [],
  invites: [],
});
const teamApi = (role = "Owner") => {
  const writeTeam = vi.fn(async (op: TeamOp) => ({
    data: {
      ...view(role),
      tools: [{ connector: "gmail", level: (op as { level: string }).level }],
    },
    source: "live" as const,
  }));
  const getTeamLive = vi.fn(async () => ({ data: view(role), source: "live" as const }));
  return { api: { ...createLiveApi(), getTeamLive, writeTeam } as unknown as Api, writeTeam };
};
const choices = (root: ParentNode, id: string) => {
  const set = root.querySelector<HTMLFieldSetElement>(
    `fieldset[aria-label="Access level for ${id}"]`,
  );
  return [...(set?.querySelectorAll("label") ?? [])].map((l) => [
    l.textContent,
    l.querySelector("input")?.value,
    l.querySelector("input")?.checked,
  ]);
};

describe("STUDIO_5 Connectors: What Tilo may do", () => {
  it("STUDIO_5 connectors each app reads Always, Ask me, Read only or Never over the server level", async () => {
    const { api } = teamApi();
    const m = await renderPage(makeApp(), api);
    expect(choices(m.container, "gmail")).toEqual([
      ["Always", "act", true],
      ["Ask me", "draft", false],
      ["Read only", "read", false],
      ["Never", "off", false],
    ]);
    expect(m.container.querySelector('[aria-label="Permissions"]')?.textContent).toContain(
      "What Tilo may do",
    );
  });

  it("STUDIO_5 connectors an owner picks Ask me with one write of the draft level", async () => {
    const { api, writeTeam } = teamApi();
    const m = await renderPage(makeApp(), api);
    const ask = m.container.querySelector<HTMLInputElement>(
      'fieldset[aria-label="Access level for gmail"] input[value="draft"]',
    );
    await act(async () => ask?.click());
    await flush();
    expect(writeTeam).toHaveBeenCalledTimes(1);
    expect(writeTeam).toHaveBeenCalledWith({ kind: "tool", connector: "gmail", level: "draft" });
    expect(choices(m.container, "gmail")[1]?.[2]).toBe(true);
  });

  it("STUDIO_5 connectors a member sees the level but cannot change it", async () => {
    const { api, writeTeam } = teamApi("Member");
    const m = await renderPage(makeApp(), api);
    const set = m.container.querySelector<HTMLFieldSetElement>(
      'fieldset[aria-label="Access level for gmail"]',
    );
    expect(set?.disabled).toBe(true);
    expect(writeTeam).not.toHaveBeenCalled();
  });

  it("STUDIO_5 connectors the live list sits beside the permissions with the server's state only", async () => {
    const fetch = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            connectors: [
              {
                id: "crm",
                name: "Actual CRM",
                state: "connected",
                state_known: true,
                scopes: [],
                expires_at: null,
              },
            ],
          }),
        ),
    );
    const m = await renderPage(makeApp(), createLiveApi({ baseUrl: "https://api.test", fetch }));
    const tile = m.container.querySelector('.park-connectors-main [aria-label="Actual CRM"]');
    expect(tile?.querySelector(".park-connectors-livestate--on")?.textContent).toBe("Connected");
    expect(tile?.textContent).toContain("Access level not available yet");
    expect(m.container.querySelector(".park-connectors-aside details")).not.toBeNull();
    expect((fetch.mock.calls as unknown[][]).map(([u]) => new URL(String(u)).pathname)).toEqual([
      "/v1/connectors",
      "/v1/people",
    ]);
  });
});
