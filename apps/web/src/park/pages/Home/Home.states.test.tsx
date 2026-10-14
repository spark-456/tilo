// @vitest-environment happy-dom
// WEB-4 acceptance: where Home gets its data and what it shows when there is none (plan sections 6 and 10:
// "Read data only through the Api via useParkApi(); render an EmptyState 'Home data is unavailable' on NotBuilt";
// "Fixtures never pass as live"). Home reads the user, today, the worlds (for the app's `dec` and `added`),
// the agenda and the ledger, and nothing else, and it never calls fetch itself.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, q, qa } from "../../../../test-support/park/componentsHarness";
import { SAMPLE_ONLY } from "../../../../test-support/park/homeCopy";
import {
  mountHome,
  pageText,
  pendingApi,
  spiedApi,
  textOf,
  todayRegion,
} from "../../../../test-support/park/homeHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import { agenda, ledger, today, user } from "../../api/fixtures";
import type { Api } from "../../api/index";
import { createLiveApi } from "../../api/liveApi";
import type { Agenda, ApiResult, Ledger, Today, User } from "../../api/types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const fixture = <T,>(data: T): Promise<ApiResult<T>> =>
  Promise.resolve({ data, source: "fixture" });

describe("WEB_4_home_states: the data comes through the Api", () => {
  it("WEB_4_home_states_reads_user_today_worlds_agenda_and_ledger_through_the_Api", async () => {
    const api = spiedApi();
    await mountHome({ api, dec: { depot: true }, app: { added: [] } });
    for (const call of [api.getUser, api.getToday, api.getWorlds, api.getAgenda, api.getLedger]) {
      expect(call).toHaveBeenCalled();
    }
    const lastWorlds = api.getWorlds.mock.calls.at(-1);
    expect(lastWorlds?.[0], "the worlds are read for the app's current decisions").toEqual({
      depot: true,
    });
    expect(lastWorlds?.[1]).toEqual([]);
  });

  it("WEB_4_home_states_never_calls_fetch_itself", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockRejectedValue(new Error("no network in tests"));
    await mountHome();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("WEB_4_home_states_every_name_and_number_shown_is_what_the_Api_returned", async () => {
    const base = createFixtureApi();
    const events: Agenda["events"] = [
      { id: "x1", d: agenda.today, s: 11, e: 12, t: "Board prep", cal: "work" },
      { id: "x2", d: agenda.today, s: 15, e: 15.5, t: "Tilo routine run", cal: "tilo" },
    ];
    const swapped: Api = {
      ...base,
      getUser: () => fixture<User>({ ...user, first: "Zed" }),
      getToday: () => fixture<Today>({ ...today, long: "Friday 25 September" }),
      getAgenda: () => fixture<Agenda>({ ...agenda, events }),
      getLedger: () => fixture<Ledger>({ ...ledger, spent: 1000, budget: 5000, forecast: 4000 }),
    };
    const { el } = await mountHome({ api: swapped });
    expect(textOf(q(el, "h1"))).toBe("Good morning, Zed.");
    expect(pageText(el).toLowerCase()).toContain("friday 25 september");
    const text = textOf(todayRegion(el));
    expect(text).toContain("Board prep");
    expect(text).toContain("11:00");
    expect(text).toContain("Google Calendar · 60 min"); // the sub-line is computed from the event
    expect(text).toContain("Tilo routine run");
    expect(text).toContain("Tilo routine"); // a Tilo calendar event says so
    expect(text).not.toContain("Supplier sync");
    expect(text).toContain("£1,000");
    expect(text).toContain("of £5,000");
    expect(text).toContain("Forecast £4,000");
    expect(text).not.toContain("£2,412");
    expect(text).not.toContain("£8,000");
  });

  it("WEB_4_home_states_a_brief_that_is_ready_says_so_under_the_event", async () => {
    const base = createFixtureApi();
    const events: Agenda["events"] = [
      { id: "b1", d: agenda.today, s: 12, e: 12.5, t: "Call with Priya", cal: "work", brief: true },
    ];
    const { el } = await mountHome({
      api: { ...base, getAgenda: () => fixture<Agenda>({ ...agenda, events }) },
    });
    expect(textOf(todayRegion(el))).toContain("Tilo’s brief is ready");
  });
});

describe("WEB_4_home_states: loading and not built", () => {
  it("WEB_4_home_states_while_loading_no_sample_value_shows", async () => {
    const { el } = await mountHome({ api: pendingApi() });
    // The page root is there from the first render (the shell's tests look for it); only the data waits.
    expect(qa(el, '[data-testid="park-page-home"]')).toHaveLength(1);
    const text = pageText(el);
    for (const sample of SAMPLE_ONLY) expect(text, sample).not.toContain(sample);
    expect(text).not.toMatch(/Good (morning|evening), \w+/);
  });

  it("WEB_4_home_states_a_live_Api_that_is_not_built_shows_Not_connected_yet", async () => {
    const { el } = await mountHome({ api: createLiveApi() });
    const text = pageText(el);
    expect(text).toContain("Home data is unavailable");
    for (const sample of SAMPLE_ONLY) expect(text, sample).not.toContain(sample);
  });

  it("WEB_4_home_states_not_built_does_not_leak_the_error_or_the_method_name", async () => {
    const { el } = await mountHome({ api: createLiveApi() });
    const text = pageText(el);
    expect(text).not.toMatch(/NotBuilt|not_built|getUser|getWorlds|getLedger|getAgenda|getToday/);
    expect(text).not.toContain("undefined");
  });

  it("WEB_4_home_states_no_console_error_while_loading_or_not_built", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await mountHome({ api: pendingApi() });
    cleanup();
    await mountHome({ api: createLiveApi() });
    expect(error).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
  });

  it("WEB_4_home_states_an_Api_that_rejects_with_any_error_never_puts_its_message_on_screen", async () => {
    const base = createFixtureApi();
    const boom = () => Promise.reject(new Error("offline-7f3"));
    const { el } = await mountHome({ api: { ...base, getWorlds: boom, getAgenda: boom } });
    expect(el.isConnected).toBe(true);
    expect(pageText(el)).not.toContain("offline-7f3");
  });
});
