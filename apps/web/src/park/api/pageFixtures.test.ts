// WEB-1d: additive page fixtures for the Park pages Team, Connectors and Profile, and the three Api reads
// that serve them (getTeamPolicy, getConnectorTerms, getProfileSettings). The values are designed
// content that the page code must not hard-code (repo rule: no scenario-specific code outside
// fixtures). They are NOT in tilo-app.js, so fixtures.parity.test.ts does not cover them; this file
// pins them twice: as literals (each with its design line) and by parsing the user's reference pages
// (design_handoff_tilo_web_app/design/Tilo App {Team,Connectors,Profile}.dc.html), so a drifting
// literal is caught too. The reference wins over any other file.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import vm from "node:vm";
import { describe, expect, expectTypeOf, it, vi } from "vitest";
import { HANDOFF_DIR } from "../../../test-support/park/prototype";
import { createFixtureApi } from "./fixtureApi";
import * as fx from "./fixtures";
import { API_METHODS } from "./index";
import type { Api } from "./index";
import { NotBuilt, createLiveApi } from "./liveApi";
import type {
  ApiResult,
  ConnectorTerms,
  NotificationRow,
  PaymentMethod,
  PlanInfo,
  ProfileInvoice,
  ProfileSession,
  ProfileSettings,
  QuietHours,
  SessionIcon,
  TeamPolicy,
} from "./types";

const ref = (name: string): string =>
  readFileSync(join(HANDOFF_DIR, "design", `Tilo App ${name}.dc.html`), "utf8");

/** First capture group of `re` in `src`; fails loudly when the reference no longer has the shape. */
const grab = (src: string, re: RegExp, what: string): string => {
  const m = re.exec(src);
  if (!m?.[1]) throw new Error(`reference page no longer holds ${what}`);
  return m[1];
};
/** Evaluate a JS literal copied from the reference (an array or object, no calls, no globals). */
const lit = <T>(src: string): T => vm.runInNewContext(`(${src})`, Object.create(null)) as T;

const TEAM = ref("Team");
const CONNECTORS = ref("Connectors");
const PROFILE = ref("Profile");

// ---------------------------------------------------------------------------------------------
// Literal values (verbatim from the reference pages; the design line is noted on each)
// ---------------------------------------------------------------------------------------------

// Tilo App Team.dc.html:122 (const LIM) and :133 (wait once a backup is added)
const TEAM_POLICY = {
  roleLimits: { Owner: "No limit", Approver: "£1,000", Member: "£250", Viewer: "—" },
  backupWait: "About 20 min",
};
// Tilo App Connectors.dc.html:125 (toast('HubSpot reconnected for 90 days'))
const CONNECTOR_TERMS = { reconnectDays: 90 };
// Tilo App Profile.dc.html:146 (const sess), :164 (invoices), :113-114 (payment), :101-103 (plan),
// :133 + :144 (notification defaults and rows), :54-55 (quiet hours)
const PROFILE_SETTINGS = {
  sessions: [
    {
      id: "mac",
      device: "MacBook Pro · Chrome",
      place: "London",
      lastActive: "active now",
      current: true,
      icon: "laptop",
    },
    {
      id: "ios",
      device: "iPhone 15 · Tilo app",
      place: "London",
      lastActive: "2 hours ago",
      note: "Face ID for approvals",
      icon: "phone",
    },
    {
      id: "ipad",
      device: "iPad · Safari",
      place: "Manchester",
      lastActive: "yesterday",
      icon: "screen",
    },
  ],
  invoices: [
    { id: "2026-09", period: "September 2026", seats: 5, amount: "£245.00", status: "Paid" },
    { id: "2026-08", period: "August 2026", seats: 5, amount: "£245.00", status: "Paid" },
    { id: "2026-07", period: "July 2026", seats: 4, amount: "£196.00", status: "Paid" },
  ],
  payment: { brand: "Visa", last4: "4242", billingEmail: "finance@northwind.co" },
  plan: {
    name: "Team",
    seats: 5,
    perks: "shared boards, two-person approvals",
    renews: "1 October",
    spendMonth: "September",
  },
  notifications: [
    {
      id: "decisions",
      label: "A decision needs you",
      description: "Budget sign-offs, gates and anything outside the company",
      phone: true,
      email: true,
      slack: true,
    },
    {
      id: "spend",
      label: "Spend goes over a limit",
      description: "A world or district passes its budget",
      phone: true,
      email: true,
      slack: false,
    },
    {
      id: "finished",
      label: "Work is ready",
      description: "Quick tasks and routine runs finish",
      phone: true,
      email: false,
      slack: true,
    },
    {
      id: "digest",
      label: "Morning digest at 08:00",
      description: "What happened overnight and what’s next",
      phone: false,
      email: true,
      slack: false,
    },
    {
      id: "weekly",
      label: "Weekly ledger summary",
      description: "Every Monday, spend and hours saved",
      phone: false,
      email: true,
      slack: true,
    },
  ],
  quiet: { on: true, start: "19:00", end: "08:00", threshold: "£1,000" },
};

const json = (v: unknown): unknown => JSON.parse(JSON.stringify(v));

describe("WEB_1d_fixtures: the three new members are exported by fixtures/index.ts", () => {
  it("WEB_1d_fixtures_team_policy_is_the_reference_team_page_values", () => {
    expect(json(fx.teamPolicy)).toEqual(TEAM_POLICY);
  });

  it("WEB_1d_fixtures_connector_terms_is_the_reference_connectors_page_value", () => {
    expect(json(fx.connectorTerms)).toEqual(CONNECTOR_TERMS);
  });

  it("WEB_1d_fixtures_profile_settings_is_the_reference_profile_page_values", () => {
    expect(json(fx.profileSettings)).toEqual(PROFILE_SETTINGS);
  });

  it("WEB_1d_fixtures_profile_settings_has_exactly_the_six_designed_parts", () => {
    expect(Object.keys(fx.profileSettings).sort()).toEqual(
      ["invoices", "notifications", "payment", "plan", "quiet", "sessions"].sort(),
    );
  });

  it("WEB_1d_fixtures_only_the_current_session_is_marked_current", () => {
    expect(fx.profileSettings.sessions.map((s) => s.current === true)).toEqual([
      true,
      false,
      false,
    ]);
    // The iPad keeps the design's icon key "screen"; the page maps it to its tablet glyph.
    expect(fx.profileSettings.sessions.map((s) => s.icon)).toEqual(["laptop", "phone", "screen"]);
  });

  it("WEB_1d_fixtures_the_decisions_row_is_the_first_notification_and_ids_are_unique", () => {
    const ids = fx.profileSettings.notifications.map((n) => n.id);
    expect(ids).toEqual(["decisions", "spend", "finished", "digest", "weekly"]);
    expect(new Set(ids).size).toBe(ids.length);
    // The page rule "Decisions need at least one channel" needs the default to have one.
    const d = fx.profileSettings.notifications[0];
    expect(d && (d.phone || d.email || d.slack)).toBe(true);
  });

  it("WEB_1d_fixtures_agree_with_the_existing_fixtures_they_sit_beside", () => {
    // roleLimits has exactly the roles of the Team fixture, in the same order (no second list of roles).
    expect(Object.keys(fx.teamPolicy.roleLimits)).toEqual(fx.team.roles);
    // The plan name is the user's plan; the Approver role limit is one the Approver people already carry.
    expect(fx.profileSettings.plan.name).toBe(fx.user.plan);
    const approverLimits = fx.team.people.filter((p) => p.role === "Approver").map((p) => p.limit);
    expect(approverLimits).toContain(fx.teamPolicy.roleLimits.Approver);
  });
});

describe("WEB_1d_reference: the literals above are what the user's reference pages say", () => {
  it("WEB_1d_reference_team_role_limits_and_backup_wait", () => {
    const limits = lit<Record<string, string>>(grab(TEAM, /const LIM = (\{[^}]*\});/, "const LIM"));
    expect(fx.teamPolicy.roleLimits).toEqual(limits);
    const wait = grab(
      TEAM,
      /wait: backups\[c\.id\] && c\.slow \? '([^']+)'/,
      "the backup wait string",
    );
    expect(fx.teamPolicy.backupWait).toBe(wait);
  });

  it("WEB_1d_reference_connectors_reconnect_toast_days", () => {
    const days = grab(
      CONNECTORS,
      /toast\('HubSpot reconnected for (\d+) days'\)/,
      "the reconnect toast",
    );
    expect(fx.connectorTerms.reconnectDays).toBe(Number(days));
    expect(`HubSpot reconnected for ${fx.connectorTerms.reconnectDays} days`).toBe(
      "HubSpot reconnected for 90 days",
    );
  });

  it("WEB_1d_reference_profile_sessions", () => {
    const sess = lit<{ k: string; t: string; s: string; ic: string; current?: boolean }[]>(
      grab(PROFILE, /const sess = (\[.*\])\.filter/, "const sess"),
    );
    const got = fx.profileSettings.sessions;
    expect(got.map((s) => s.id)).toEqual(sess.map((d) => d.k));
    expect(got.map((s) => s.device)).toEqual(sess.map((d) => d.t));
    expect(got.map((s) => s.icon)).toEqual(sess.map((d) => d.ic));
    expect(got.map((s) => s.current === true)).toEqual(sess.map((d) => d.current === true));
    // The sub line the page shows is place, last active and the note, joined with " · ".
    expect(got.map((s) => [s.place, s.lastActive, s.note].filter(Boolean).join(" · "))).toEqual(
      sess.map((d) => d.s),
    );
  });

  it("WEB_1d_reference_profile_invoices", () => {
    const rows = lit<[string, string][]>(
      grab(PROFILE, /invoices: (\[\[.*?\]\])\.map/, "the invoices list"),
    );
    const got = fx.profileSettings.invoices;
    expect(got.map((i) => `${i.period} · ${i.seats} seats`)).toEqual(rows.map(([t]) => t));
    expect(got.map((i) => i.amount)).toEqual(rows.map(([, amt]) => amt));
    // The download toast is 'Downloaded ' + t.split(' ·')[0] + ' invoice'.
    expect(got.map((i) => `Downloaded ${i.period} invoice`)).toEqual(
      rows.map(([t]) => `Downloaded ${t.split(" ·")[0]} invoice`),
    );
    // The status chip is the literal "Paid" in the reference markup.
    expect(PROFILE).toContain(">Paid</span>");
    expect(got.every((i) => i.status === "Paid")).toBe(true);
  });

  it("WEB_1d_reference_profile_payment_and_plan_text", () => {
    const { payment, plan } = fx.profileSettings;
    expect(`${payment.brand} ending ${payment.last4}`).toBe(
      grab(PROFILE, />(Visa ending \d{4})</, "the card line"),
    );
    expect(`Invoices go to ${payment.billingEmail}`).toBe(
      grab(PROFILE, />(Invoices go to [^<]+)</, "the invoice email line"),
    );
    expect(plan.name).toBe(grab(PROFILE, />PLAN<\/span>\s*<span[^>]*>([^<]+)</, "the plan name"));
    expect(`${plan.seats} seats, ${plan.perks}. Renews ${plan.renews}.`).toBe(
      grab(PROFILE, />(\d+ seats, [^<]+)</, "the plan blurb"),
    );
    expect(`AGENT SPEND · ${plan.spendMonth.toUpperCase()}`).toBe(
      grab(PROFILE, />(AGENT SPEND · [^<]+)</, "the spend eyebrow"),
    );
  });

  it("WEB_1d_reference_profile_notification_rows_and_defaults", () => {
    const rows = lit<[string, string, string][]>(
      grab(PROFILE, /const NOTIF = (\[.*\]);/, "const NOTIF"),
    );
    const channels = lit<string[]>(grab(PROFILE, /const CH = (\[.*?\]),/, "const CH"));
    const state = lit<Record<string, number[]>>(
      grab(PROFILE, /notif: (\{ decisions[^}]*\})/, "the notification defaults"),
    );
    expect(channels).toEqual(["Phone", "Email", "Slack"]);
    const got = fx.profileSettings.notifications;
    expect(got.map((n) => [n.id, n.label, n.description])).toEqual(rows);
    expect(got.map((n) => [n.phone, n.email, n.slack].map(Number))).toEqual(
      rows.map(([k]) => state[k]),
    );
  });

  it("WEB_1d_reference_profile_quiet_hours", () => {
    const q = fx.profileSettings.quiet;
    expect(`Quiet hours · ${q.start} to ${q.end}`).toBe(
      grab(PROFILE, />(Quiet hours · [^<]+)</, "the quiet hours title"),
    );
    expect(`Phone stays silent, except decisions over ${q.threshold}.`).toBe(
      grab(PROFILE, />(Phone stays silent, except decisions over [^<]+)</, "the quiet hours line"),
    );
    expect(q.on).toBe(grab(PROFILE, /quiet: (true|false)/, "the quiet default") === "true");
  });
});

describe("WEB_1d_types: the new shapes (type-level; checked by the typecheck)", () => {
  it("WEB_1d_types_team_policy_and_connector_terms", () => {
    expectTypeOf<TeamPolicy>().toEqualTypeOf<{
      roleLimits: Record<"Owner" | "Approver" | "Member" | "Viewer", string>;
      backupWait: string;
    }>();
    expectTypeOf<ConnectorTerms>().toEqualTypeOf<{ reconnectDays: number }>();
  });

  it("WEB_1d_types_profile_settings_parts", () => {
    expectTypeOf<SessionIcon>().toEqualTypeOf<"laptop" | "phone" | "screen">();
    expectTypeOf<ProfileSession["icon"]>().toEqualTypeOf<SessionIcon>();
    expectTypeOf<ProfileSession["current"]>().toEqualTypeOf<boolean | undefined>();
    expectTypeOf<ProfileSession["note"]>().toEqualTypeOf<string | undefined>();
    expectTypeOf<ProfileInvoice["seats"]>().toEqualTypeOf<number>();
    expectTypeOf<ProfileInvoice["status"]>().toEqualTypeOf<"Paid">();
    expectTypeOf<PaymentMethod>().toEqualTypeOf<{
      brand: string;
      last4: string;
      billingEmail: string;
    }>();
    expectTypeOf<PlanInfo["seats"]>().toEqualTypeOf<number>();
    expectTypeOf<NotificationRow["id"]>().toEqualTypeOf<
      "decisions" | "spend" | "finished" | "digest" | "weekly"
    >();
    expectTypeOf<NotificationRow["phone"]>().toEqualTypeOf<boolean>();
    expectTypeOf<QuietHours>().toEqualTypeOf<{
      on: boolean;
      start: string;
      end: string;
      threshold: string;
    }>();
    expectTypeOf<ProfileSettings>().toEqualTypeOf<{
      sessions: ProfileSession[];
      invoices: ProfileInvoice[];
      payment: PaymentMethod;
      plan: PlanInfo;
      notifications: NotificationRow[];
      quiet: QuietHours;
    }>();
  });

  it("WEB_1d_types_the_fixtures_and_the_api_reads_are_typed_with_them", () => {
    expectTypeOf(fx.teamPolicy).toEqualTypeOf<TeamPolicy>();
    expectTypeOf(fx.connectorTerms).toEqualTypeOf<ConnectorTerms>();
    expectTypeOf(fx.profileSettings).toEqualTypeOf<ProfileSettings>();
    expectTypeOf<Api["getTeamPolicy"]>().toEqualTypeOf<() => Promise<ApiResult<TeamPolicy>>>();
    expectTypeOf<Api["getConnectorTerms"]>().toEqualTypeOf<
      () => Promise<ApiResult<ConnectorTerms>>
    >();
    expectTypeOf<Api["getProfileSettings"]>().toEqualTypeOf<
      () => Promise<ApiResult<ProfileSettings>>
    >();
  });
});

describe("WEB_1d_api: the three reads on the fixture Api", () => {
  it("WEB_1d_api_methods_are_in_the_one_list", () => {
    for (const m of ["getTeamPolicy", "getConnectorTerms", "getProfileSettings"]) {
      expect(API_METHODS, m).toContain(m);
    }
  });

  it("WEB_1d_api_reads_resolve_the_fixture_with_source_fixture_and_only_data_and_source", async () => {
    const api = createFixtureApi();
    const reads = [
      ["getTeamPolicy", await api.getTeamPolicy(), TEAM_POLICY],
      ["getConnectorTerms", await api.getConnectorTerms(), CONNECTOR_TERMS],
      ["getProfileSettings", await api.getProfileSettings(), PROFILE_SETTINGS],
    ] as const;
    for (const [name, result, expected] of reads) {
      expect(result.source, `${name}.source`).toBe("fixture");
      expect(json(result.data), `${name}.data`).toEqual(expected);
      expect(Object.keys(result).sort(), `${name} result keys`).toEqual(["data", "source"]);
    }
  });

  it("WEB_1d_api_reads_return_promises", () => {
    const api = createFixtureApi();
    expect(api.getTeamPolicy()).toBeInstanceOf(Promise);
    expect(api.getConnectorTerms()).toBeInstanceOf(Promise);
    expect(api.getProfileSettings()).toBeInstanceOf(Promise);
  });

  it("WEB_1d_api_reads_hand_out_copies_not_the_shared_objects", async () => {
    const api = createFixtureApi();
    const policy = (await api.getTeamPolicy()).data;
    const terms = (await api.getConnectorTerms()).data;
    const settings = (await api.getProfileSettings()).data;
    expect(policy).not.toBe(fx.teamPolicy);
    expect(policy.roleLimits).not.toBe(fx.teamPolicy.roleLimits);
    expect(terms).not.toBe(fx.connectorTerms);
    expect(settings).not.toBe(fx.profileSettings);
    expect(settings.sessions).not.toBe(fx.profileSettings.sessions);
    expect(settings.sessions[0]).not.toBe(fx.profileSettings.sessions[0]);
    expect(settings.notifications[0]).not.toBe(fx.profileSettings.notifications[0]);
  });

  it("WEB_1d_api_a_caller_changing_a_result_changes_no_fixture_and_no_later_read", async () => {
    const before = JSON.stringify([fx.teamPolicy, fx.connectorTerms, fx.profileSettings]);
    const api = createFixtureApi();
    const policy = (await api.getTeamPolicy()).data;
    const terms = (await api.getConnectorTerms()).data;
    const settings = (await api.getProfileSettings()).data;
    policy.roleLimits.Member = "changed by a caller";
    policy.backupWait = "changed by a caller";
    terms.reconnectDays = 1;
    settings.sessions.length = 0;
    settings.invoices[0] = { ...settings.invoices[0], amount: "£0.00" } as ProfileInvoice;
    settings.payment.last4 = "0000";
    settings.plan.seats = 99;
    const first = settings.notifications[0];
    if (first) first.email = false;
    settings.quiet.on = false;
    expect(JSON.stringify([fx.teamPolicy, fx.connectorTerms, fx.profileSettings])).toBe(before);
    expect(json((await api.getTeamPolicy()).data)).toEqual(TEAM_POLICY);
    expect(json((await api.getConnectorTerms()).data)).toEqual(CONNECTOR_TERMS);
    expect(json((await api.getProfileSettings()).data)).toEqual(PROFILE_SETTINGS);
  });

  it("WEB_1d_api_two_instances_do_not_share_state", async () => {
    const a = createFixtureApi();
    const b = createFixtureApi();
    (await a.getProfileSettings()).data.plan.seats = 99;
    (await a.getTeamPolicy()).data.roleLimits.Owner = "changed";
    (await a.getConnectorTerms()).data.reconnectDays = 1;
    expect(json((await b.getProfileSettings()).data)).toEqual(PROFILE_SETTINGS);
    expect(json((await b.getTeamPolicy()).data)).toEqual(TEAM_POLICY);
    expect(json((await b.getConnectorTerms()).data)).toEqual(CONNECTOR_TERMS);
  });

  it("WEB_1d_api_reads_never_mutate_frozen_fixtures_and_make_no_network_request", async () => {
    const freeze = (v: unknown): void => {
      if (v && typeof v === "object" && !Object.isFrozen(v)) {
        Object.freeze(v);
        for (const x of Object.values(v)) freeze(x);
      }
    };
    freeze(fx.teamPolicy);
    freeze(fx.connectorTerms);
    freeze(fx.profileSettings);
    const fetchSpy = vi.fn(async () => {
      throw new Error("WEB-1d: the fixture api must not touch the network");
    });
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const api = createFixtureApi();
      expect(json((await api.getTeamPolicy()).data)).toEqual(TEAM_POLICY);
      expect(json((await api.getConnectorTerms()).data)).toEqual(CONNECTOR_TERMS);
      expect(json((await api.getProfileSettings()).data)).toEqual(PROFILE_SETTINGS);
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("WEB_1d_api: the live Api rejects NotBuilt for the three reads", () => {
  it.each(["getTeamPolicy", "getConnectorTerms", "getProfileSettings"] as const)(
    "WEB_1d_live_api_%s_rejects_NotBuilt_and_returns_no_sample_value",
    async (name) => {
      const p = createLiveApi()[name]();
      expect(p).toBeInstanceOf(Promise);
      const outcome = await p.then(
        (value) => ({ resolved: value }),
        (e: unknown) => ({ rejected: e }),
      );
      expect(outcome).not.toHaveProperty("resolved");
      const { rejected } = outcome as { rejected: NotBuilt };
      expect(rejected).toBeInstanceOf(NotBuilt);
      expect(rejected.code).toBe("not_built");
    },
  );
});

describe("WEB_1d_files: the new fixtures are hand-written, one place for the scenario content", () => {
  it.each(["teamPolicy", "connectorTerms", "profileSettings"])(
    "WEB_1d_files_%s_is_a_hand_written_file_that_says_it_is_not_generated",
    (file) => {
      const src = readFileSync(join(__dirname, "fixtures", `${file}.ts`), "utf8");
      const header = src.split(/\r?\n/).slice(0, 6).join("\n");
      expect(header).toMatch(/hand-written/i);
      expect(header).toMatch(/not generated/i);
      expect(header).not.toMatch(/^\/\/ GENERATED/m);
    },
  );

  it("WEB_1d_files_the_generator_does_not_write_the_new_files", () => {
    const gen = readFileSync(
      join(__dirname, "..", "..", "..", "scripts", "park-fixtures.mjs"),
      "utf8",
    );
    expect(gen).not.toMatch(/teamPolicy|connectorTerms|profileSettings/);
  });
});
