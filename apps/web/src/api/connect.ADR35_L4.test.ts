// ADR35_L4 / FR_CON_02 (LC-02, LC-03): the web's connect flow. The state of Google's link is saved before the page leaves;
// the callback posts only when the returned state is the saved one, clears it, and says the result in plain words.
import { describe, expect, it } from "vitest";
import { type ConnectFlow, createConnectFlow, stateOf } from "./connect";
import { TiloApiError } from "./http";

const state = (): string => `${"abcdef".repeat(5)}-_`;
const link = (s: string): string =>
  `https://accounts.google.com/o/oauth2/v2/auth?client_id=x&state=${s}`;
const KEY = "tilo.google.connect.state";

function memory(): Storage {
  const map = new Map<string, string>();
  return {
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => void map.set(k, v),
    removeItem: (k) => void map.delete(k),
    clear: () => map.clear(),
    key: () => null,
    get length() {
      return map.size;
    },
  };
}

function rig(
  post: (path: string, body: unknown) => Promise<unknown>,
  get: () => Promise<unknown> = async () => ({ connectors: [] }),
) {
  const store = memory();
  const posts: { path: string; body: unknown }[] = [];
  const flow: ConnectFlow = createConnectFlow(
    {
      getJson: () => get(),
      postJson: (path, body) => {
        posts.push({ path, body });
        return post(path, body);
      },
    },
    () => store,
  );
  return { flow, store, posts };
}

const refused = (status: number | null, refusal: string | null) => async () => {
  throw new TiloApiError("x", status, false, true, null, false, refusal);
};

describe("ADR35_L4_FR_CON_02_web_connect_flow", () => {
  it("ADR35_L4_FR_CON_02_start_saves_the_links_state_then_hands_back_the_link", async () => {
    const s = state();
    const r = rig(async () => ({ authorize_url: link(s) }));
    const got = await r.flow.start("gmail", ["read"]);
    expect(got).toEqual({ kind: "redirect", url: link(s) });
    expect(r.store.getItem(KEY)).toBe(s);
    expect(r.posts).toEqual([
      { path: "/v1/connectors/connect", body: { connector: "gmail", capabilities: ["read"] } },
    ]);
  });

  it("ADR35_L4_FR_CON_02_open_leaves_through_the_injected_navigation_only", () => {
    const seen: string[] = [];
    const flow = createConnectFlow(
      { getJson: async () => ({}), postJson: async () => ({}) },
      () => memory(),
      (url) => void seen.push(url),
    );
    flow.open(link(state()));
    expect(seen).toEqual([link(state())]);
  });

  it("ADR35_L4_FR_CON_02_start_with_nothing_missing_saves_nothing", async () => {
    const r = rig(async () => ({ authorize_url: null }));
    expect(await r.flow.start("gmail", ["read"])).toEqual({ kind: "nothing_missing" });
    expect(r.store.length).toBe(0);
  });

  it.each([
    ["a link to another host", `https://evil.example/o/oauth2/v2/auth?state=${state()}`],
    ["http", `http://accounts.google.com/o/oauth2/v2/auth?state=${state()}`],
    ["no state", "https://accounts.google.com/o/oauth2/v2/auth?client_id=x"],
    ["a short state", link("short")],
    ["a non-string", 7],
  ])("ADR35_L4_FR_CON_02_start_refuses_%s_and_saves_nothing", async (_n, url) => {
    const r = rig(async () => ({ authorize_url: url }));
    expect(await r.flow.start("gmail", ["read"])).toEqual({ kind: "failed" });
    expect(r.store.length).toBe(0);
    expect(stateOf(String(url))).toBeNull();
  });

  it("ADR35_L4_FR_CON_02_start_that_fails_or_cannot_save_is_failed", async () => {
    const r = rig(refused(503, null));
    expect(await r.flow.start("gmail", ["read"])).toEqual({ kind: "failed" });
    const none = createConnectFlow(
      { getJson: async () => ({}), postJson: async () => ({ authorize_url: link(state()) }) },
      () => null,
    );
    expect(await none.start("gmail", ["read"])).toEqual({ kind: "failed" });
  });

  it("ADR35_L4_FR_CON_02_finish_posts_only_when_the_returned_state_is_the_saved_one", async () => {
    const s = state();
    const r = rig(async () => ({ connector: "gmail", scope_lines: ["Read your Gmail messages"] }));
    r.store.setItem(KEY, s);
    expect(await r.flow.finish({ state: `${s}x`, code: "4/abc" })).toEqual({ kind: "start_again" });
    expect(r.posts).toEqual([]); // nothing was posted
    expect(r.store.getItem(KEY)).toBe(s);
    expect(await r.flow.finish({ state: s, code: "4/abc" })).toEqual({
      kind: "connected",
      lines: ["Read your Gmail messages"],
    });
    expect(r.posts).toEqual([
      { path: "/v1/connectors/callback", body: { state: s, code: "4/abc" } },
    ]);
    expect(r.store.getItem(KEY)).toBeNull(); // cleared
    expect(await r.flow.finish({ state: s, code: "4/abc" })).toEqual({ kind: "start_again" }); // spent
    expect(r.posts).toHaveLength(1);
  });

  it("ADR35_L4_FR_CON_02_finish_with_nothing_saved_posts_nothing", async () => {
    const r = rig(async () => ({}));
    expect(await r.flow.finish({ state: state(), code: "4/abc" })).toEqual({ kind: "start_again" });
    expect(r.posts).toEqual([]);
  });

  it("ADR35_L4_FR_CON_02_finish_sends_googles_error_word_when_the_person_said_no", async () => {
    const s = state();
    const r = rig(refused(400, "not_granted"));
    r.store.setItem(KEY, s);
    expect(await r.flow.finish({ state: s, error: "access_denied" })).toEqual({
      kind: "not_granted",
    });
    expect(r.posts[0]?.body).toEqual({ state: s, error: "access_denied" });
  });

  it.each([
    [400, "start_again", "start_again"],
    [400, "wrong_account", "wrong_account"],
    [400, "other", "start_again"],
    [503, "unknown", "unavailable"],
    [503, null, "unavailable"],
    [null, null, "unavailable"],
  ] as const)(
    "ADR35_L4_FR_CON_02_finish_failure_%s_%s_reads_as_%s",
    async (status, refusal, kind) => {
      const s = state();
      const r = rig(refused(status, refusal));
      r.store.setItem(KEY, s);
      expect((await r.flow.finish({ state: s, code: "4/abc" })).kind).toBe(kind);
    },
  );

  it("ADR35_L4_FR_CON_02_finish_with_an_unreadable_answer_is_unavailable", async () => {
    const s = state();
    const r = rig(async () => ({ connector: "gmail", scope_lines: [] }));
    r.store.setItem(KEY, s);
    expect((await r.flow.finish({ state: s, code: "4/abc" })).kind).toBe("unavailable");
  });

  it("ADR35_L4_FR_CON_02_list_keeps_the_three_google_connectors_in_order", async () => {
    const r = rig(
      async () => ({}),
      async () => ({
        connectors: [
          { id: "lovable", name: "Lovable", state: "connected" },
          { id: "google_calendar", name: "Google Calendar", state: "attention" },
          { id: "gmail", name: "Gmail", state: "connected" },
          { id: "google_drive", name: "Google Drive", state: "weird" },
        ],
      }),
    );
    expect(await r.flow.list()).toEqual([
      { id: "gmail", name: "Gmail", state: "connected" },
      { id: "google_drive", name: "Google Drive", state: "available" },
      { id: "google_calendar", name: "Google Calendar", state: "attention" },
    ]);
  });

  it("ADR35_L4_FR_CON_02_disconnect_is_true_only_on_a_confirmed_answer", async () => {
    const ok = rig(async () => ({
      disconnected: true,
      revoked_at_provider: true,
      revoke_pending: false,
    }));
    expect(await ok.flow.disconnect("gmail")).toBe(true);
    expect(ok.posts).toEqual([{ path: "/v1/connectors/disconnect", body: { connector: "gmail" } }]);
    expect(await rig(refused(503, null)).flow.disconnect("gmail")).toBe(false);
  });
});
