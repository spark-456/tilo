// WEB-1a (plan section 6.1; HR-1..HR-7): the live Api is a stub. Every method rejects with NotBuilt
// (code "not_built") and never returns a fixture value, so a configured deployment cannot show sample
// numbers as if real. The method list is one exported const, API_METHODS, so a method added to the
// interface without a live stub fails here.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { callTable, invoke } from "../../../test-support/park/apiCalls";
import { createFixtureApi } from "./fixtureApi";
import { API_METHODS } from "./index";
import { NotBuilt, createLiveApi } from "./liveApi";

const READS = [
  "getUser",
  "getToday",
  "getDecisions",
  "getWorlds",
  "getPlans",
  "getSkills",
  "getLearn",
  "getLedger",
  "getAgenda",
  "getTeam",
  "getTeamLive",
  "getConnectors",
  "getNotifications",
  "getTeamPolicy",
  "getConnectorTerms",
  "getProfileSettings",
  "getUserSettings",
  "getBuildHandoff",
] as const;
const WRITES = [
  "decide",
  "undo",
  "startWorld",
  "saveSkill",
  "captureSkill",
  "proposeVersion",
  "setToolLevel",
  "bookSlot",
  "addBackup",
  "setPref",
  "writeTeam",
  "saveUserSettings",
  "submitFeedback",
] as const;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WEB_1a_api_methods: one list of methods", () => {
  it("WEB_1a_api_methods_const_lists_every_read_and_write_once", () => {
    expect([...API_METHODS].sort()).toEqual([...READS, ...WRITES].sort());
    expect(new Set(API_METHODS).size).toBe(API_METHODS.length);
    expect(API_METHODS).toHaveLength(31);
  });

  it("WEB_1a_api_methods_the_test_call_table_covers_every_method", () => {
    // A method added to API_METHODS must get a call here; compile-time too (CallTable is keyed by it).
    expect(Object.keys(callTable()).sort()).toEqual([...API_METHODS].sort());
  });

  it("WEB_1a_api_methods_the_fixture_api_implements_every_method", () => {
    const api = createFixtureApi();
    for (const m of API_METHODS) expect(typeof api[m], `fixtureApi.${m}`).toBe("function");
  });
});

describe("WEB_1a_live_api: every method rejects NotBuilt", () => {
  it("WEB_1a_live_api_has_a_stub_for_every_method", () => {
    const api = createLiveApi();
    for (const m of API_METHODS) expect(typeof api[m], `liveApi.${m} is missing`).toBe("function");
  });

  it("WEB_1a_live_api_every_method_returns_a_promise_that_rejects_with_NotBuilt", async () => {
    const api = createLiveApi();
    const args = callTable();
    for (const m of API_METHODS) {
      const p = invoke(api, m, args);
      expect(p, `${m} must return a rejected Promise, not throw or resolve`).toBeInstanceOf(
        Promise,
      );
      const err = await (p as Promise<unknown>).then(
        (value) => ({ resolved: value }),
        (e: unknown) => e,
      );
      expect(err, `${m} must not resolve with a value`).not.toHaveProperty("resolved");
      expect(err, `${m}`).toBeInstanceOf(NotBuilt);
      expect(err, `${m}`).toBeInstanceOf(Error);
      expect((err as NotBuilt).code, `${m}`).toBe("not_built");
    }
  });

  it("WEB_1a_live_api_makes_no_network_request_yet", async () => {
    const fetchSpy = vi.fn(async () => {
      throw new Error("WEB-1a: the live api is a stub and must not touch the network");
    });
    vi.stubGlobal("fetch", fetchSpy);
    const api = createLiveApi();
    const args = callTable();
    for (const m of API_METHODS) {
      await Promise.resolve(invoke(api, m, args)).catch(() => undefined);
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("WEB_1a_live_api_cannot_leak_a_fixture_value_it_does_not_import_the_fixtures", () => {
    const src = readFileSync(join(__dirname, "liveApi.ts"), "utf8");
    expect(src).not.toMatch(/from\s+["']\.\/fixtures/);
    expect(src).not.toMatch(/from\s+["']\.\/fixtureApi/);
  });

  it("WEB_1a_live_api_NotBuilt_is_a_named_error_class", () => {
    expect(typeof NotBuilt).toBe("function");
    expect(NotBuilt.prototype).toBeInstanceOf(Error);
  });
});
