// M1 / FR_MTG_09 / FR_CON_02 (ADR-0024 decision 2, ADR-0035 LC-02): the web's meeting-host sign-in rides the existing
// connect flow. The same state guard applies; the host's status is read from `GET /v1/connectors` and is "unknown"
// unless the server says it read it (`state_known`).
import { describe, expect, it } from "vitest";
import { type ConnectFlow, createConnectFlow } from "./connect";
import { TiloApiError } from "./http";

const state = (): string => `${"ghijkl".repeat(5)}-_`;
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

const hostRow = (over: Record<string, unknown> = {}) => ({
  id: "meeting_host",
  name: "Tilo meeting host",
  state: "connected",
  state_known: true,
  ...over,
});
const listing =
  (...rows: unknown[]) =>
  async () => ({ connectors: rows });

describe("M1_FR_MTG_09_meeting_host_connect_flow", () => {
  it("M1_FR_MTG_09_start_asks_for_the_send_capability_and_saves_the_state_before_leaving", async () => {
    const s = state();
    const r = rig(async () => ({ authorize_url: link(s) }));
    expect(await r.flow.start("meeting_host", ["send"])).toEqual({
      kind: "redirect",
      url: link(s),
    });
    expect(r.store.getItem(KEY)).toBe(s);
    expect(r.posts).toEqual([
      {
        path: "/v1/connectors/connect",
        body: { connector: "meeting_host", capabilities: ["send"] },
      },
    ]);
  });

  it("M1_FR_MTG_09_the_callback_still_posts_only_a_state_this_tab_saved", async () => {
    const s = state();
    const r = rig(async () => ({ connector: "meeting_host", scope_lines: ["Create meetings"] }));
    r.store.setItem(KEY, s);
    expect(await r.flow.finish({ state: `${s}x`, code: "4/abc" })).toEqual({
      kind: "start_again",
    });
    expect(r.posts).toEqual([]);
    expect(await r.flow.finish({ state: s, code: "4/abc" })).toEqual({
      kind: "connected",
      lines: ["Create meetings"],
      connector: "meeting_host",
    });
    expect(r.store.getItem(KEY)).toBeNull();
  });

  it("M1_FR_MTG_09_only_the_known_host_id_is_carried_out_of_a_callback_answer", async () => {
    const s = state();
    const r = rig(async () => ({ connector: "<b>host</b>", scope_lines: ["x"] }));
    r.store.setItem(KEY, s);
    expect(await r.flow.finish({ state: s, code: "4/abc" })).toEqual({
      kind: "connected",
      lines: ["x"],
    });
  });

  it.each([
    ["connected", true, "connected"],
    ["attention", true, "attention"],
    ["available", true, "available"],
    ["available", false, "unknown"], // an unwired view: "available" would be a guess
    ["connected", false, "unknown"],
    ["weird", true, "unknown"],
  ] as const)("M1_FR_MTG_09_status_%s_known_%s_reads_as_%s", async (stateWord, known, expected) => {
    const r = rig(async () => ({}), listing(hostRow({ state: stateWord, state_known: known })));
    expect(await r.flow.meetingHost()).toBe(expected);
  });

  it("M1_FR_MTG_09_a_listing_without_the_host_is_unknown_and_a_failed_read_throws", async () => {
    const none = rig(async () => ({}), listing({ id: "gmail", name: "Gmail", state: "connected" }));
    expect(await none.flow.meetingHost()).toBe("unknown");
    const bad = rig(
      async () => ({}),
      async () => {
        throw new TiloApiError("x", 503, true, true, null, false, "unknown");
      },
    );
    await expect(bad.flow.meetingHost()).rejects.toBeInstanceOf(TiloApiError);
  });

  it("M1_FR_MTG_09_the_three_google_rows_do_not_change", async () => {
    const r = rig(
      async () => ({}),
      listing(hostRow(), { id: "gmail", name: "Gmail", state: "connected" }),
    );
    expect(await r.flow.list()).toEqual([{ id: "gmail", name: "Gmail", state: "connected" }]);
  });

  it("M1_FR_MTG_09_disconnect_names_only_the_host_connector", async () => {
    const r = rig(async () => ({
      disconnected: true,
      revoked_at_provider: true,
      revoke_pending: false,
    }));
    expect(await r.flow.disconnect("meeting_host")).toBe("done");
    expect(r.posts).toEqual([
      { path: "/v1/connectors/disconnect", body: { connector: "meeting_host" } },
    ]);
  });
});
