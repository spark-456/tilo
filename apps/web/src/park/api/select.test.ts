// WEB-1a (plan section 6.1; PRD 9.4 HR-1..HR-7): parkApi(env) picks the Api. VITE_TILO_API_URL unset
// (or blank) is the fixture Api, source "fixture"; set, it is the live Api, whose methods reject with
// NotBuilt until each endpoint exists. A configured deployment never silently serves sample numbers.
// Defaults: a blank or whitespace-only value counts as unset, as in src/api/config.ts (chooseClient).
import fc from "fast-check";
import { afterEach, describe, expect, it, vi } from "vitest";
import { callTable, invoke } from "../../../test-support/park/apiCalls";
import { chooseClient } from "../../api/config";
import { HttpClient } from "../../api/http";
import * as fx from "./fixtures";
import { API_METHODS } from "./index";
import { NotBuilt } from "./liveApi";
import { parkApi } from "./select";

const LIVE_ENV = { VITE_TILO_API_URL: "https://api.example.test" };

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WEB_1a_select: no API url means fixtures, labelled as such", () => {
  const UNSET: { VITE_TILO_API_URL?: string }[] = [
    {},
    { VITE_TILO_API_URL: "" },
    { VITE_TILO_API_URL: "   " },
  ];
  it.each(UNSET)("WEB_1a_select_unset_env_%o_gives_source_fixture_everywhere", async (env) => {
    const api = parkApi(env);
    const args = callTable();
    for (const m of API_METHODS) {
      const result = (await invoke(api, m, args)) as { source: string; data: unknown };
      expect(result.source, `${m}.source`).toBe("fixture");
    }
    expect((await api.getUser()).data).toEqual(fx.user);
    expect((await api.getSkills()).data).toEqual(fx.skills);
  });
});

describe("WEB_1a_select: an API url means the live Api and no sample values", () => {
  it("WEB_1a_select_with_url_every_method_rejects_NotBuilt", async () => {
    // WIRE-1/2/3: getLedger (GET /costs), getWorlds (GET /worlds), getDecisions (GET /cards) and decide (the answer
    // route) are built (liveApi.wire1/wire2/wire3 tests).
    const api = parkApi(LIVE_ENV);
    const args = callTable();
    for (const m of API_METHODS.filter(
      (x) =>
        ![
          "getLedger",
          "getWorlds",
          "getDecisions",
          "decide",
          "startWorld",
          "getProfileSettings",
          "getSkills",
          "getLearn",
          "saveSkill",
          "captureSkill",
          "proposeVersion",
          "setPref",
        ].includes(x),
    )) {
      const p = invoke(api, m, args);
      expect(p, `${m} returns a Promise`).toBeInstanceOf(Promise);
      const outcome = await (p as Promise<unknown>).then(
        (value) => ({ resolved: value }),
        (e: unknown) => ({ rejected: e }),
      );
      expect(outcome, `${m} resolved with a value: sample data must not appear`).not.toHaveProperty(
        "resolved",
      );
      const { rejected } = outcome as { rejected: NotBuilt };
      expect(rejected, `${m}`).toBeInstanceOf(NotBuilt);
      expect(rejected.code, `${m}`).toBe("not_built");
    }
  });

  it("WEB_1a_select_with_url_no_network_request_is_made_for_an_unbuilt_method", async () => {
    const fetchSpy = vi.fn(async () => {
      throw new Error("WEB-1a: nothing to fetch yet");
    });
    vi.stubGlobal("fetch", fetchSpy);
    const api = parkApi(LIVE_ENV);
    await expect(api.getUser()).rejects.toBeInstanceOf(NotBuilt);
    // WIRE-3 built `decide` (a key the live feed never served is a TiloApiError, liveApi.wire3.test.ts); `undo` has no route.
    await expect(api.undo("depot")).rejects.toBeInstanceOf(NotBuilt);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("WEB_1a_select_url_with_surrounding_spaces_is_still_live", async () => {
    await expect(
      parkApi({ VITE_TILO_API_URL: "  https://api.example.test  " }).getUser(),
    ).rejects.toBeInstanceOf(NotBuilt);
  });

  it("WEB_1a_select_property_same_switch_as_the_app_client_config", async () => {
    // parkApi is live exactly when src/api/config.ts picks the HTTP client for the same value.
    const blank = fc
      .array(fc.constantFrom(" ", "\t", "\n"), { maxLength: 5 })
      .map((chars) => chars.join(""));
    const nonBlank = fc.string({ minLength: 1, maxLength: 30 }).filter((s) => s.trim().length > 0);
    await fc.assert(
      fc.asyncProperty(fc.oneof(blank, nonBlank), async (url) => {
        const isHttp = chooseClient({ apiUrl: url, search: "" }) instanceof HttpClient;
        const outcome = await parkApi({ VITE_TILO_API_URL: url })
          .getUser()
          .then(
            (r) => r.source,
            (e: unknown) => (e instanceof NotBuilt ? "not_built" : "other"),
          );
        expect(outcome).toBe(isHttp ? "not_built" : "fixture");
      }),
      { numRuns: 60 },
    );
  });
});
