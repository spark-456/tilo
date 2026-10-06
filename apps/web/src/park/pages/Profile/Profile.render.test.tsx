// @vitest-environment happy-dom
// WEB-12 render + copy (plan section 10; design "Tilo App Profile.dc.html", inventory.md "Tilo App
// Profile.dc.html"): every designed element is on every tab, every visible string and aria-label is the
// design's, the data comes only through the park Api, and the page never passes fixture numbers off as live.
// Interface pinned here, for the builder:
// - `ProfilePage({ app })` from ./ProfilePage (named export, no `api` prop: data via useParkApi(), tests wrap
//   the page in <ParkProvider api={spy}>); `import "./Profile.css"`. h1 is the user's name; the nav is
//   `<nav aria-label="Settings">` with five <button>s (icon + label), aria-current="page" on the open tab;
//   each tab is a labelled <section> (aria-label = the tab's section name below); the first tab is
//   `params.tab` when it names a tab, else "profile". The five tab ids are profile, notifications,
//   appearance, security, billing (README).
// - the page is the design's own: no "Sample data" chip and no "recorded for the demo" line (shell-only,
//   WEB-3b). The S-* screens the plan maps Profile onto (S-22 Settings, S-16 Channels, S-15 Autonomy) are
//   information only: the design links to none of them, so the page has none.
// - a choice (time of day, motion) is a button with aria-pressed, as in the design; aria-checked is accepted.
// - labels: the extra aria-label of a radiogroup/group wrapper is tolerated (a reused SegmentedControl names
//   its group), nothing else beyond the design's set.
import { afterEach, describe, expect, it } from "vitest";
import { makeApp } from "../../../../test-support/park/profileApp";
import { createLiveApi } from "../../api/liveApi";
import {
  APPEARANCE_COPY,
  ARIA_LABELS,
  BILLING_COPY,
  CONNECTORS,
  FIELDS,
  INVOICES,
  NOTIF,
  NOTIF_COPY,
  SECURITY_COPY,
  SESSIONS,
  STRINGS,
  SUBTITLE,
  TABS,
  type TabId,
  USER,
  switchLabel,
} from "./profileExpect";
import {
  buttonNamed,
  buttonWith,
  cleanup,
  fieldInput,
  openTab,
  ownText,
  pressedOf,
  region,
  renderProfile,
  settingsNav,
  spyApi,
  strings,
  switchNamed,
  tabNamed,
  text,
} from "./testApp";

afterEach(cleanup);

const labelsOf = (root: ParentNode): string[] =>
  [...root.querySelectorAll("[aria-label]")]
    .filter((e) => !["radiogroup", "group"].includes(e.getAttribute("role") ?? ""))
    .map((e) => e.getAttribute("aria-label") ?? "")
    .sort();
const h2s = (root: ParentNode): string[] => [...root.querySelectorAll("h2")].map(text);

describe("WEB_12_profile_render: the frame (header and tabs)", () => {
  it("WEB_12_profile_header_has_avatar_name_subtitle_and_connectors_button", async () => {
    const { root } = await renderProfile(makeApp());
    expect([...root.querySelectorAll("h1")].map(text), "one h1: the name").toEqual([USER.name]);
    const got = strings(root);
    expect(got.has(USER.initials), "72px avatar initials").toBe(true);
    expect(got.has(SUBTITLE)).toBe(true);
    const connectors = buttonNamed(root, CONNECTORS);
    expect(connectors.querySelector("svg"), "plug icon before the label").not.toBeNull();
    expect(connectors.disabled).toBe(false);
  });

  it("WEB_12_profile_nav_has_five_tabs_with_icons_and_the_first_is_current", async () => {
    const { root } = await renderProfile(makeApp());
    const nav = settingsNav(root);
    expect(nav.tagName).toBe("NAV");
    const tabs = [...nav.querySelectorAll("button")];
    expect(tabs.map(text)).toEqual(TABS.map((t) => t.label));
    for (const t of tabs) expect(t.querySelector("svg"), `${text(t)}: icon`).not.toBeNull();
    expect(tabs.map((t) => t.getAttribute("aria-current"))).toEqual([
      "page",
      null,
      null,
      null,
      null,
    ]);
  });

  it.each(TABS.map((t) => [t.id, t.label] as const))(
    "WEB_12_profile_params_tab_%s_opens_that_tab_first",
    async (id, label) => {
      const { root } = await renderProfile(makeApp({ params: { tab: id } }));
      expect(tabNamed(root, label).getAttribute("aria-current")).toBe("page");
      const section = TABS.find((t) => t.id === id)?.section ?? "";
      expect(root.querySelector(`section[aria-label="${section}"]`), section).not.toBeNull();
    },
  );

  it("WEB_12_profile_has_one_filled_primary_button_on_profile_and_billing_UX_1", async () => {
    const { root } = await renderProfile(makeApp());
    const primaries = (): number => root.querySelectorAll("button.park-btn--primary").length;
    expect(primaries(), "profile: Save changes").toBe(1);
    expect(text(root.querySelector("button.park-btn--primary"))).toBe("Save changes");
    for (const id of ["notifications", "appearance", "security"] as const) {
      await openTab(root, TABS.find((t) => t.id === id)?.label ?? "");
      expect(primaries(), id).toBe(0);
    }
    await openTab(root, "Plan and billing");
    expect(primaries(), "billing: Compare plans").toBe(1);
    expect(text(root.querySelector("button.park-btn--primary"))).toBe("Compare plans");
  });
});

describe("WEB_12_profile_render: Profile tab", () => {
  it("WEB_12_profile_form_has_six_labelled_inputs_with_helps_and_the_user_values", async () => {
    const { root } = await renderProfile(makeApp());
    const card = region(root, "Profile");
    expect(h2s(card)).toEqual(["Profile"]);
    expect(card.querySelectorAll("input")).toHaveLength(FIELDS.length);
    for (const [label, help, value] of FIELDS) {
      const input = fieldInput(root, label);
      expect(input.value, label).toBe(value);
      expect(input.type, label).toMatch(/^(text|email)?$/);
      expect(strings(input.closest("label") as Element).has(help), `${label}: help line`).toBe(
        true,
      );
    }
  });

  it("WEB_12_profile_cancel_and_save_buttons_are_enabled_and_in_the_footer", async () => {
    const { root } = await renderProfile(makeApp());
    const cancel = buttonNamed(root, "Cancel");
    const save = buttonNamed(root, "Save changes");
    expect(cancel.disabled).toBe(false);
    expect(save.disabled).toBe(false);
    expect(cancel.nextElementSibling, "Save changes follows Cancel").toBe(save);
  });
});

describe("WEB_12_profile_render: Notifications tab", () => {
  it("WEB_12_profile_notifications_matrix_is_five_rows_by_three_channels_with_design_state", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Notifications");
    const card = region(root, "Notifications");
    expect(h2s(card)).toEqual(["Notifications"]);
    const got = strings(card);
    for (const c of NOTIF_COPY.columns) expect(got.has(c), c).toBe(true);
    const want = NOTIF.flatMap((n) =>
      n[3].map((on, i) => [switchLabel(n[1], ["Phone", "Email", "Slack"][i] ?? ""), String(on)]),
    );
    const matrix = [...card.querySelectorAll('[role="switch"]')]
      .filter((s) => s.getAttribute("aria-label") !== NOTIF_COPY.quietLabel)
      .map((s) => [s.getAttribute("aria-label"), s.getAttribute("aria-checked")]);
    expect(matrix, "15 switches in row-major order, with the initial matrix").toEqual(want);
    for (const [, label, sub] of NOTIF) {
      expect(got.has(label) && got.has(sub), label).toBe(true);
    }
  });

  it("WEB_12_profile_quiet_hours_row_has_icon_text_and_an_on_switch", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Notifications");
    const quiet = switchNamed(root, NOTIF_COPY.quietLabel);
    expect(quiet.getAttribute("aria-checked")).toBe("true");
    const row = quiet.parentElement as HTMLElement;
    expect(strings(row)).toEqual(new Set([NOTIF_COPY.quiet, NOTIF_COPY.quietSub]));
    expect(row.querySelector("svg"), "moon icon in the 36px tile").not.toBeNull();
  });
});

describe("WEB_12_profile_render: Appearance tab", () => {
  it("WEB_12_profile_time_of_day_cards_day_is_pressed_and_each_has_a_three_block_swatch", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Appearance");
    const card = region(root, "Appearance");
    expect(h2s(card)).toEqual(["Appearance"]);
    const [day, night] = APPEARANCE_COPY.times.map(([label]) => buttonWith(card, label));
    for (const [btn, [label, sub]] of [
      [day, APPEARANCE_COPY.times[0]],
      [night, APPEARANCE_COPY.times[1]],
    ] as const) {
      expect(strings(btn as Element), label).toEqual(new Set([label, sub]));
      const swatch = (btn as Element).firstElementChild as Element;
      expect(swatch.children, `${label}: swatch with three blocks`).toHaveLength(3);
    }
    expect(pressedOf(day as Element)).toBe("true");
    expect(pressedOf(night as Element)).toBe("false");
  });

  it("WEB_12_profile_night_app_presses_the_night_card", async () => {
    const { root } = await renderProfile(makeApp({ time: "night", night: true }));
    await openTab(root, "Appearance");
    expect(pressedOf(buttonWith(root, "Lamps and glow"))).toBe("true");
    expect(pressedOf(buttonWith(root, "Bright lawns"))).toBe("false");
  });

  it.each([
    ["lively", "Lively"],
    ["calm", "Calm"],
    ["still", "Still"],
  ] as const)(
    "WEB_12_profile_motion_%s_presses_%s_and_shows_its_help_line",
    async (motion, label) => {
      const { root } = await renderProfile(makeApp({ motion }));
      await openTab(root, "Appearance");
      for (const l of APPEARANCE_COPY.motions) {
        expect(pressedOf(buttonNamed(root, l)), l).toBe(String(l === label));
      }
      const got = strings(root);
      for (const [k, line] of Object.entries(APPEARANCE_COPY.help)) {
        expect(got.has(line), `${k} help shown only for ${motion}`).toBe(k === motion);
      }
    },
  );
});

describe("WEB_12_profile_render: Security tab", () => {
  it("WEB_12_profile_security_rows_actions_and_three_sessions", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Security");
    const card = region(root, "Security");
    expect(h2s(card)).toEqual(["Security"]);
    const got = strings(card);
    for (const [t, s, a] of SECURITY_COPY.rows) {
      expect(got.has(t) && got.has(s), t).toBe(true);
      expect(buttonNamed(card, a).disabled, a).toBe(false);
    }
    expect(got.has(SECURITY_COPY.signedIn)).toBe(true);
    expect(buttonNamed(card, SECURITY_COPY.everywhere)).toBeDefined();
    for (const [t, s] of SESSIONS) expect(got.has(t) && got.has(s), t).toBe(true);
    expect(
      [...card.querySelectorAll("*")].filter((e) => ownText(e) === SECURITY_COPY.thisDevice),
      "one 'This device' chip",
    ).toHaveLength(1);
    expect(
      [...card.querySelectorAll("button")].filter((b) => text(b) === SECURITY_COPY.signOut),
      "Sign out on the two other devices, none on this one",
    ).toHaveLength(2);
    expect(card.querySelectorAll("svg").length, "an icon tile on every row").toBeGreaterThanOrEqual(
      SECURITY_COPY.rows.length + SESSIONS.length,
    );
  });
});

describe("WEB_12_profile_render: Plan and billing tab", () => {
  it("WEB_12_profile_billing_has_plan_spend_payment_cards_and_three_paid_invoices", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Plan and billing");
    const card = region(root, "Plan and billing");
    expect(h2s(card), "only the Invoices heading").toEqual([BILLING_COPY.invoices]);
    const ledger = buttonWith(card, BILLING_COPY.openLedger);
    expect(strings(ledger)).toEqual(
      new Set([
        BILLING_COPY.spendLabel,
        BILLING_COPY.spend,
        BILLING_COPY.of,
        BILLING_COPY.openLedger,
      ]),
    );
    const bar = [...ledger.querySelectorAll<HTMLElement>("[style]")].find((e) => e.style.width);
    expect(bar?.style.width, "£2,412 of £8,000 is 30%").toBe("30%");
    const downloads = [...card.querySelectorAll<HTMLElement>('button[aria-label="Download"]')];
    expect(downloads).toHaveLength(INVOICES.length);
    for (const d of downloads) expect(d.querySelector("svg"), "download icon").not.toBeNull();
    expect(
      [...card.querySelectorAll("*")].filter((e) => ownText(e) === BILLING_COPY.paid),
    ).toHaveLength(INVOICES.length);
    expect(card.querySelector("svg"), "card icon in the payment tile").not.toBeNull();
  });
});

describe("WEB_12_profile_copy: every visible string and aria-label is the design's", () => {
  it.each(TABS.map((t) => [t.id, t.label] as const))(
    "WEB_12_profile_exact_copy_%s_tab_has_no_missing_and_no_extra_string",
    async (id, label) => {
      const { root } = await renderProfile(makeApp());
      if (id !== "profile") await openTab(root, label);
      const got = strings(root);
      const want = new Set(STRINGS[id as TabId]);
      expect({
        missing: [...want].filter((s) => !got.has(s)),
        extra: [...got].filter((s) => !want.has(s)),
      }).toEqual({ missing: [], extra: [] });
    },
  );

  it.each(TABS.map((t) => [t.id, t.label] as const))(
    "WEB_12_profile_aria_labels_%s_tab_are_exactly_the_designs",
    async (id, label) => {
      const { root } = await renderProfile(makeApp());
      if (id !== "profile") await openTab(root, label);
      expect(labelsOf(root)).toEqual([...ARIA_LABELS[id as TabId]].sort());
    },
  );

  it("WEB_12_profile_exact_copy_keeps_the_curly_apostrophe_the_middle_dot_and_the_pound", async () => {
    const { root } = await renderProfile(makeApp());
    expect(strings(root).has("Tilo won’t book outside these")).toBe(true);
    expect(strings(root).has(SUBTITLE)).toBe(true);
    await openTab(root, "Notifications");
    expect(strings(root).has("What happened overnight and what’s next")).toBe(true);
    expect(strings(root).has("Phone stays silent, except decisions over £1,000.")).toBe(true);
    expect(strings(root).has("Phone stays silent, except decisions over £1,000")).toBe(false);
  });

  it("WEB_12_profile_the_page_has_no_sample_data_chip_and_no_recorded_for_the_demo_line", async () => {
    // Shell-only (WEB-3b): the page renders neither, so a shell that shows them owns the wording.
    const { root } = await renderProfile(makeApp());
    for (const t of TABS) {
      if (t.id !== "profile") await openTab(root, t.label);
      expect(root.textContent ?? "", t.id).not.toMatch(/sample data|recorded for the demo/i);
    }
  });

  it("WEB_12_profile_makes_no_live_or_real_time_claim", async () => {
    const { root } = await renderProfile(makeApp());
    for (const t of TABS) {
      if (t.id !== "profile") await openTab(root, t.label);
      expect(root.textContent ?? "", t.id).not.toMatch(/\blive\b|real[- ]time|just now|updated/i);
    }
  });
});

describe("WEB_12_profile_data: through the park Api only", () => {
  it("WEB_12_profile_reads_the_user_through_getUser_and_calls_nothing_that_writes", async () => {
    const api = spyApi();
    const { root } = await renderProfile(makeApp(), api);
    expect(api.getUser).toHaveBeenCalled();
    expect(root.textContent).toContain(USER.name);
    for (const m of [
      "decide",
      "undo",
      "startWorld",
      "saveSkill",
      "setToolLevel",
      "bookSlot",
      "addBackup",
      "setPref",
    ] as const) {
      expect(api[m], `${m}: effects go through the AppCtx, not the Api`).not.toHaveBeenCalled();
    }
  });

  it("WEB_12_profile_not_connected_shows_not_connected_yet_and_no_sample_user", async () => {
    // Plan 6.1: a page whose endpoint is NotBuilt says so; it never shows sample numbers as if real.
    const { root } = await renderProfile(makeApp(), createLiveApi());
    expect(root.textContent).toContain("Not connected yet");
    for (const s of [USER.name, USER.email, USER.title, "Northwind Ops"]) {
      expect(root.textContent, s).not.toContain(s);
    }
    expect(root.querySelectorAll("h1"), "the page keeps a heading").toHaveLength(1);
    expect(root.querySelectorAll("input"), "no form of sample values").toHaveLength(0);
  });

  it("WEB_12_profile_night_renders_the_same_content", async () => {
    const day = await renderProfile(makeApp());
    const dayStrings = strings(day.root);
    cleanup();
    const night = await renderProfile(makeApp({ time: "night", night: true }));
    expect(strings(night.root)).toEqual(dayStrings);
  });
});
