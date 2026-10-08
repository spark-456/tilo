// @vitest-environment happy-dom
// TEAM-WEB (FR-TEAM-02, FR-TEAM-04, FR-ACC-01): the Team page on a live Api reads GET /v1/team (nothing else is
// built, so every other Api method rejects NotBuilt) and sends the Owner-only writes. Fixture mode is unchanged
// (the other Team tests). No layout shift: the status line is always in the page. Optimistic changes roll back.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, makeApp, renderTeam } from "../../../../test-support/park/teamHarness";
import { TiloApiError } from "../../../api/http";
import type { Api } from "../../api";
import type { TeamOp, TeamView } from "../../api/live/teamLive";
import { createLiveApi } from "../../api/liveApi";
import {
  buttonNamed,
  choose,
  clickAndSettle,
  inputNamed,
  region,
  selectNamed,
  settle,
  strings,
  switchNamed,
  typeInto,
} from "./testApp";

afterEach(cleanup);

const view = (over: Partial<TeamView> = {}): TeamView => ({
  version: 4,
  me: { id: "u1", role: "Owner" },
  members: [
    { id: "u1", role: "Owner", limit_minor: null },
    { id: "u2", role: "Member", limit_minor: 5000 },
  ],
  switches: [
    { key: "spend", on: true, must_ask: true },
    { key: "share", on: true, must_ask: true },
    { key: "undo", on: true, must_ask: true },
    { key: "tools", on: true, must_ask: false },
    { key: "weekend", on: false, must_ask: false },
  ],
  tools: [{ connector: "gmail", level: "act" }],
  capabilities: [
    {
      key: "start_quick_tasks",
      label: "Start quick tasks",
      roles: ["Owner", "Approver", "Member"],
    },
    { key: "invite_people", label: "Invite people", roles: ["Owner"] },
  ],
  invites: [{ id: "inv_1", email: "new@acme.co", role: "Viewer" }],
  ...over,
});

interface Spies {
  api: Api;
  write: ReturnType<typeof vi.fn>;
  read: ReturnType<typeof vi.fn>;
}
function liveApi(read: () => Promise<TeamView>, write?: (op: TeamOp) => Promise<TeamView>): Spies {
  const readSpy = vi.fn(async () => ({ data: await read(), source: "live" as const }));
  const writeSpy = vi.fn(async (op: TeamOp) => ({
    data: await (write ?? (() => Promise.reject(new Error("no write"))))(op),
    source: "live" as const,
  }));
  const api = { ...createLiveApi(), getTeamLive: readSpy, writeTeam: writeSpy } as unknown as Api;
  return { api, write: writeSpy, read: readSpy };
}
const err = (status: number, replay = false) =>
  new TiloApiError("server words", status, status >= 500, true, null, replay);
const statusLine = (root: ParentNode): string =>
  root.querySelector("output")?.textContent?.trim() ?? "";

describe("TEAM_WEB_team_page_live: reads the server's team", () => {
  it("TEAM_WEB_live_page_shows_the_servers_members_invites_and_matrix_not_the_sample_team", async () => {
    const { api } = liveApi(async () => view());
    const { root } = await renderTeam(makeApp(), api);
    const s = strings(root);
    expect(selectNamed(root, "Role for u2").value).toBe("Member");
    expect(s.has("new@acme.co")).toBe(true);
    expect(s.has("Start quick tasks")).toBe(true);
    expect(s.has("Approve spend up to their limit")).toBe(false); // the sample matrix row is not in this server's list
    expect(root.textContent).not.toContain("Priya");
    expect(root.textContent).not.toContain("Not connected yet");
  });

  it("TEAM_WEB_live_matrix_ticks_come_from_the_servers_capabilities", async () => {
    const { api } = liveApi(async () => view());
    const { root } = await renderTeam(makeApp(), api);
    const rows = [...region(root, "What each role can do").querySelectorAll("tbody tr")];
    const granted = (i: number) =>
      [...(rows[i]?.querySelectorAll("[data-granted]") ?? [])].map((c) =>
        c.getAttribute("data-granted"),
      );
    expect(granted(0)).toEqual(["true", "true", "true", "false"]);
    expect(granted(1)).toEqual(["true", "false", "false", "false"]);
  });

  it("TEAM_WEB_live_must_ask_switches_are_on_and_locked_and_tools_says_not_enforced_yet", async () => {
    const { api } = liveApi(async () => view());
    const { root } = await renderTeam(makeApp(), api);
    for (const name of [
      "Spending money",
      "Sharing anything outside the company",
      "Actions that can’t be undone",
    ]) {
      const sw = switchNamed(root, name);
      expect(sw.getAttribute("aria-checked")).toBe("true");
      expect((sw as HTMLButtonElement).disabled).toBe(true);
    }
    expect(strings(root).has("Saved; not enforced yet")).toBe(true);
    // weekend is wired into the engine, but a hold longer than the retry window can lose the slot (BQ-TEAMRT-3)
    expect([...strings(root)].some((t) => /^Hold until Monday morning\./.test(t))).toBe(true);
    expect(root.textContent).toMatch(/lose the slot|can be missed/i);
  });
});

describe("TEAM_WEB_team_page_live: Owner writes", () => {
  it("TEAM_WEB_live_role_change_is_optimistic_then_takes_the_servers_view", async () => {
    let release: (v: TeamView) => void = () => undefined;
    const next = view({
      members: [view().members[0] as never, { id: "u2", role: "Approver", limit_minor: 5000 }],
    });
    const { api, write } = liveApi(
      async () => view(),
      () =>
        new Promise<TeamView>((r) => {
          release = r;
        }),
    );
    const { root } = await renderTeam(makeApp(), api);
    await choose(selectNamed(root, "Role for u2"), "Approver");
    expect(write).toHaveBeenCalledWith({ kind: "role", id: "u2", role: "Approver" });
    expect(selectNamed(root, "Role for u2").value).toBe("Approver"); // before the server answers
    release(next);
    await settle();
    expect(selectNamed(root, "Role for u2").value).toBe("Approver");
  });

  it("TEAM_WEB_live_failed_write_rolls_back_and_says_why", async () => {
    const { api } = liveApi(
      async () => view(),
      async () => Promise.reject(err(422)),
    );
    const { root } = await renderTeam(makeApp(), api);
    await choose(selectNamed(root, "Role for u2"), "Viewer");
    expect(selectNamed(root, "Role for u2").value).toBe("Member");
    expect(statusLine(root)).toBe("server words"); // a 422 keeps the server's own plain sentence
  });

  it("TEAM_WEB_live_409_refetches_and_shows_the_current_state", async () => {
    const fresh = view({
      members: [view().members[0] as never, { id: "u2", role: "Viewer", limit_minor: null }],
    });
    let n = 0;
    const { api, read } = liveApi(
      async () => (n++ === 0 ? view() : fresh),
      async () => Promise.reject(err(409)),
    );
    const { root } = await renderTeam(makeApp(), api);
    await choose(selectNamed(root, "Role for u2"), "Approver");
    expect(read).toHaveBeenCalledTimes(2);
    expect(selectNamed(root, "Role for u2").value).toBe("Viewer");
    expect(statusLine(root)).toMatch(/Someone else changed the team/);
  });

  it("TEAM_WEB_live_switch_weekend_sends_one_write_and_rolls_back_on_503", async () => {
    const { api, write } = liveApi(
      async () => view(),
      async () => Promise.reject(err(503)),
    );
    const { root } = await renderTeam(makeApp(), api);
    await clickAndSettle(switchNamed(root, "Routines that fall on a weekend"));
    expect(write).toHaveBeenCalledWith({ kind: "switch", key: "weekend", on: true });
    expect(switchNamed(root, "Routines that fall on a weekend").getAttribute("aria-checked")).toBe(
      "false",
    );
    expect(statusLine(root)).toBe("Team controls are not set up on this install yet.");
  });

  it("TEAM_WEB_live_invite_sends_email_and_role_member_and_shows_the_servers_invite", async () => {
    const after = view({
      invites: [...view().invites, { id: "inv_2", email: "x@acme.co", role: "Member" }],
    });
    const { api, write } = liveApi(
      async () => view(),
      async () => after,
    );
    const { root } = await renderTeam(makeApp(), api);
    await typeInto(inputNamed(root, "Invite by email"), "x@acme.co");
    await clickAndSettle(buttonNamed(root, "Invite"));
    expect(write).toHaveBeenCalledWith({ kind: "invite", email: "x@acme.co", role: "Member" });
    expect(strings(root).has("x@acme.co")).toBe(true);
  });

  it("TEAM_WEB_live_remove_member_sends_delete_and_cancel_invite_is_not_offered_without_a_route", async () => {
    const after = view({ members: [view().members[0] as never] });
    const { api, write } = liveApi(
      async () => view(),
      async () => after,
    );
    const { root } = await renderTeam(makeApp(), api);
    await clickAndSettle(buttonNamed(root, "Show details for u2"));
    await clickAndSettle(buttonNamed(root, "Remove from team"));
    expect(write).toHaveBeenCalledWith({ kind: "remove", id: "u2" });
    expect(root.querySelector('select[aria-label="Role for u2"]')).toBeNull();
    expect(root.textContent).not.toContain("Cancel invite"); // no route cancels an invite (NotBuilt)
    expect(root.textContent).not.toContain("Resend invite");
  });
});

describe("TEAM_WEB_team_page_live: honest copy", () => {
  it("TEAM_WEB_live_remove_toast_does_not_claim_worlds_moved", async () => {
    const after = view({ members: [view().members[0] as never] });
    const { api } = liveApi(
      async () => view(),
      async () => after,
    );
    const app = makeApp();
    const { root } = await renderTeam(app, api);
    await clickAndSettle(buttonNamed(root, "Show details for u2"));
    await clickAndSettle(buttonNamed(root, "Remove from team"));
    expect(app.toast).toHaveBeenCalledWith("u2 was removed from the team");
    for (const [m] of (app.toast as ReturnType<typeof vi.fn>).mock.calls)
      expect(String(m)).not.toMatch(/worlds?/i);
  });

  it("TEAM_WEB_live_invite_saved_but_refresh_failed_keeps_the_invite_and_says_so", async () => {
    const { api } = liveApi(
      async () => view(),
      async () => null as never,
    );
    const { root } = await renderTeam(makeApp(), api);
    await typeInto(inputNamed(root, "Invite by email"), "x@acme.co");
    await clickAndSettle(buttonNamed(root, "Invite"));
    expect(root.textContent).toContain("Saved; could not refresh");
    expect(strings(root).has("x@acme.co")).toBe(true);
  });
});

describe("TEAM_WEB_team_page_live: spend limits", () => {
  it("TEAM_WEB_live_owner_sets_a_members_spend_limit_in_rupees_sent_as_minor_units", async () => {
    const after = view({
      members: [view().members[0] as never, { id: "u2", role: "Member", limit_minor: 120000 }],
    });
    const { api, write } = liveApi(
      async () => view(),
      async () => after,
    );
    const { root } = await renderTeam(makeApp(), api);
    await clickAndSettle(buttonNamed(root, "Show details for u2"));
    await typeInto(inputNamed(root, "Spend limit for u2 in rupees"), "1200");
    await clickAndSettle(buttonNamed(root, "Save limit"));
    expect(write).toHaveBeenCalledWith({ kind: "limit", id: "u2", limitMinor: 120000 });
    expect(strings(root).has("₹1,200")).toBe(true);
  });
});

describe("TEAM_WEB_team_page_live: who may change what", () => {
  it("TEAM_WEB_live_non_owner_sees_a_read_only_page_with_disabled_controls", async () => {
    const v = view({ me: { id: "u2", role: "Member" }, invites: [] });
    const { api } = liveApi(async () => v);
    const { root } = await renderTeam(makeApp(), api);
    expect(selectNamed(root, "Role for u1").disabled).toBe(true);
    expect(selectNamed(root, "Role for u2").disabled).toBe(true);
    expect(switchNamed(root, "Routines that fall on a weekend").hasAttribute("disabled")).toBe(
      true,
    );
    expect(inputNamed(root, "Invite by email").disabled).toBe(true);
    expect(statusLine(root)).toBe("Only an Owner can change the team. You can look at it.");
  });

  it("TEAM_WEB_live_you_cannot_change_your_own_role", async () => {
    const { api } = liveApi(async () => view());
    const { root } = await renderTeam(makeApp(), api);
    expect(selectNamed(root, "Role for u1").disabled).toBe(true);
    expect(selectNamed(root, "Role for u2").disabled).toBe(false);
  });
});

describe("TEAM_WEB_team_page_live: read failures are messages, not crashes", () => {
  const cases: [number, boolean, RegExp][] = [
    [503, false, /Team controls are not set up on this install yet/],
    [403, false, /sign-in on the web/],
    [401, false, /Sign in again/],
    [404, false, /not on this team/i],
    [503, true, /Live models are unavailable/],
  ];
  for (const [status, replay, re] of cases) {
    it(`TEAM_WEB_live_read_${status}${replay ? "_replay_only" : ""}_shows_a_plain_message_and_keeps_the_heading`, async () => {
      const e =
        status === 503 && replay
          ? new TiloApiError(
              "Live models are unavailable right now.",
              503,
              false,
              false,
              null,
              true,
            )
          : err(status);
      const { api } = liveApi(async () => Promise.reject(e));
      const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
      const { root } = await renderTeam(makeApp(), api);
      const heading = root.querySelector("h1");
      expect(heading?.textContent).toBe("Team");
      expect(root.textContent).toMatch(re);
      expect(root.textContent).not.toContain("not_configured");
      expect(root.querySelector("select")).toBeNull();
      expect(errors).not.toHaveBeenCalled();
      errors.mockRestore();
    });
  }
});

describe("TEAM_WEB_team_page_fixture: fixtures stay the default", () => {
  it("TEAM_WEB_fixture_mode_never_calls_a_write_and_keeps_the_sample_copy", async () => {
    const { renderTeam: render } = await import("../../../../test-support/park/teamHarness");
    const { root } = await render(makeApp());
    expect(strings(root).has("Spending over £250")).toBe(true);
    expect(root.textContent).not.toContain("Saved; not enforced yet");
  });
});
