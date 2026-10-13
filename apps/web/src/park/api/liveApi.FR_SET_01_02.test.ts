// FR-SET-01 / FR-SET-02 (ADR-0039): the live Api reads and writes the person's own UserSettings through
// GET and PUT /v1/me/settings. It names no owner or org, awaits the write, and says `live` only for a document
// the server answered with. A failure stays a TiloApiError; nothing falls back to defaults.
import { describe, expect, it, vi } from "vitest";
import { TiloApiError } from "../../api/http";
import { createFixtureApi } from "./fixtureApi";
import { userSettings } from "./fixtures";
import { NotBuilt, createLiveApi } from "./liveApi";

const BASE = "https://api.example";
const { owner_id: _o, org_id: _g, updated_at: _u, ...rest } = userSettings;
const update = { ...rest, version: 1 };
const reply = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const live = (fetch: typeof globalThis.fetch) => createLiveApi({ baseUrl: BASE, fetch });

describe("FR_SET_01_live_settings_api", () => {
  it("test_FR_SET_01_get_reads_the_stored_document_from_v1_me_settings_and_says_live", async () => {
    const fetch = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
      reply(userSettings),
    );
    const r = await live(fetch).getUserSettings();
    expect(r).toEqual({ data: userSettings, source: "live" });
    expect(String(fetch.mock.calls[0]?.[0])).toBe(`${BASE}/v1/me/settings`);
  });

  it("test_FR_SET_01_put_sends_the_whole_update_once_and_returns_the_stored_document", async () => {
    const stored = { ...userSettings, version: 2 };
    const fetch = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => reply(stored));
    const r = await live(fetch).saveUserSettings(update);
    expect(r).toEqual({ data: stored, source: "live" });
    expect(fetch).toHaveBeenCalledTimes(1);
    const init = fetch.mock.calls[0]?.[1];
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual(update);
    expect(Object.keys(JSON.parse(String(init?.body)))).not.toContain("owner_id");
  });

  it.each([
    [401, null],
    [409, "version_conflict"],
    [422, "invalid_settings"],
    [500, null],
  ])("test_FR_SET_01_a_%i_answer_is_a_typed_error_never_defaults", async (status, code) => {
    const fetch = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
      reply({ detail: code ?? "x", code }, status),
    );
    const err = await live(fetch)
      .saveUserSettings(update)
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(TiloApiError);
    expect((err as TiloApiError).status).toBe(status);
    expect((err as TiloApiError).code).toBe(code);
    const read = await live(fetch)
      .getUserSettings()
      .catch((e: unknown) => e);
    expect(read).toBeInstanceOf(TiloApiError);
  });

  it("test_FR_SET_01_a_reply_that_is_not_a_settings_document_is_unreadable_not_saved", async () => {
    const fetch = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
      reply({ ok: true }),
    );
    await expect(live(fetch).saveUserSettings(update)).rejects.toBeInstanceOf(TiloApiError);
    await expect(live(fetch).getUserSettings()).rejects.toBeInstanceOf(TiloApiError);
  });

  it("test_FR_SET_01_without_an_api_url_nothing_is_read_or_saved", async () => {
    const api = createLiveApi();
    await expect(api.getUserSettings()).rejects.toBeInstanceOf(NotBuilt);
    await expect(api.saveUserSettings(update)).rejects.toBeInstanceOf(NotBuilt);
  });

  it("test_FR_SET_01_the_fixture_answer_is_never_live_so_a_page_cannot_show_it_as_saved", async () => {
    const api = createFixtureApi();
    expect((await api.getUserSettings()).source).toBe("fixture");
    expect((await api.saveUserSettings(update)).source).toBe("fixture");
  });
});
