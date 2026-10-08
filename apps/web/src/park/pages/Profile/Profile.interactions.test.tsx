// @vitest-environment happy-dom
// WEB-12 interactions (design "Tilo App Profile.dc.html" script, inventory.md toasts; README AppCtx contract):
// tabs, the profile form, the notification matrix and quiet hours, appearance (setPref), security sessions,
// plan and billing. Each toast is the design's exact string with no extra argument; navigation is app.go
// only, with the design's page and no params; the design persists exactly two prefs (time and motion, both
// through app.setPref(key, value)); notification channels, quiet hours and the form are page state that
// calls nothing; Profile has no approve control, so app.decide and app.addWorld are never called.
// Local state lives at page level, as in the design, so it survives a tab switch.
import fc from "fast-check";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { makeApp } from "../../../../test-support/park/profileApp";
import {
  APPEARANCE_COPY,
  BILLING_COPY,
  FIELDS,
  INVOICES,
  NOTIF,
  NOTIF_COPY,
  PROFILE_COPY,
  SECURITY_COPY,
  SESSIONS,
  SUBTITLE,
  TABS,
  USER,
  switchLabel,
} from "../../../../test-support/park/profileExpect";
import { clearProfileStore } from "./profileStore";
import {
  buttonNamed,
  buttonWith,
  cleanup,
  clickAndSettle,
  fieldInput,
  openTab,
  pressedOf,
  profileTree,
  region,
  renderProfile,
  settle,
  spyApi,
  strings,
  switchNamed,
  switchStates,
  tabNamed,
  text,
  typeInto,
} from "./testApp";

afterEach(cleanup);

const CHANNELS = ["Phone", "Email", "Slack"] as const;
const heading = (root: ParentNode): string => text(root.querySelector("h1"));
const matrixLabels = NOTIF.flatMap((n) => CHANNELS.map((c) => switchLabel(n[1], c)));
const matrix = (root: ParentNode): string[] =>
  switchStates(root)
    .filter(([l]) => l !== NOTIF_COPY.quietLabel)
    .map(([, on]) => on);
const signOutButtons = (root: ParentNode): HTMLButtonElement[] =>
  [...root.querySelectorAll<HTMLButtonElement>("button")].filter(
    (b) => text(b) === SECURITY_COPY.signOut,
  );

// FR-SET-01: Save now persists to localStorage and the store's memory; every test starts from an empty store.
beforeEach(() => {
  localStorage.clear();
  clearProfileStore();
});

describe("WEB_12_profile_tabs: local state, no navigation", () => {
  it("WEB_12_profile_clicking_each_tab_opens_its_section_and_moves_the_current_marker", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    for (const t of TABS) {
      await openTab(root, t.label);
      expect(tabNamed(root, t.label).getAttribute("aria-current"), t.id).toBe("page");
      expect(
        [...root.querySelectorAll("nav button[aria-current]")].map(text),
        "exactly one current tab",
      ).toEqual([t.label]);
      const open = TABS.filter((o) => root.querySelector(`section[aria-label="${o.section}"]`));
      expect(
        open.map((o) => o.id),
        "only the open tab's section is in the page",
      ).toEqual([t.id]);
    }
    expect(app.go, "tabs are page state, not routes").not.toHaveBeenCalled();
    expect(app.toast).not.toHaveBeenCalled();
  });

  it("WEB_12_profile_state_survives_a_tab_switch", async () => {
    const { root } = await renderProfile(makeApp());
    await typeInto(fieldInput(root, "Job title"), "Head of Operations");
    await openTab(root, "Notifications");
    await clickAndSettle(switchNamed(root, switchLabel("Weekly ledger summary", "Phone")));
    await clickAndSettle(switchNamed(root, NOTIF_COPY.quietLabel));
    await openTab(root, "Security");
    await clickAndSettle(signOutButtons(root)[0] as Element);
    await openTab(root, "Profile");
    expect(fieldInput(root, "Job title").value).toBe("Head of Operations");
    await openTab(root, "Notifications");
    expect(
      switchNamed(root, switchLabel("Weekly ledger summary", "Phone")).getAttribute("aria-checked"),
    ).toBe("true");
    expect(switchNamed(root, NOTIF_COPY.quietLabel).getAttribute("aria-checked")).toBe("false");
    await openTab(root, "Security");
    expect(strings(root).has(SESSIONS[1][0])).toBe(false);
  });
});

describe("WEB_12_profile_header: Connectors", () => {
  it("WEB_12_profile_connectors_button_goes_to_connectors_without_params", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await clickAndSettle(buttonNamed(root, "Connectors"));
    expect(app.go).toHaveBeenCalledTimes(1);
    expect(app.go.mock.calls[0]?.[0]).toBe("connectors");
    expect(app.go.mock.calls[0]?.[1] ?? {}).toEqual({});
  });
});

describe("WEB_12_profile_form: edit, cancel, save", () => {
  it("WEB_12_profile_typing_a_name_and_title_updates_the_heading_and_subtitle_at_once", async () => {
    const { root } = await renderProfile(makeApp());
    await typeInto(fieldInput(root, "Full name"), "Alexandra Morgan");
    expect(heading(root)).toBe("Alexandra Morgan");
    await typeInto(fieldInput(root, "Job title"), "Head of Operations");
    expect(strings(root).has("Head of Operations · Northwind Ops · Owner on the Team plan")).toBe(
      true,
    );
    expect(fieldInput(root, "Full name").value).toBe("Alexandra Morgan");
  });

  it("WEB_12_profile_each_field_edits_independently", async () => {
    const { root } = await renderProfile(makeApp());
    await typeInto(fieldInput(root, "Time zone"), "Europe/Paris (GMT+2)");
    for (const [label, , value] of FIELDS) {
      expect(fieldInput(root, label).value, label).toBe(
        label === "Time zone" ? "Europe/Paris (GMT+2)" : value,
      );
    }
  });

  it("WEB_12_profile_cancel_restores_every_field_the_heading_and_the_subtitle_without_a_toast", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await typeInto(fieldInput(root, "Full name"), "Someone Else");
    await typeInto(fieldInput(root, "Language"), "Deutsch");
    await clickAndSettle(buttonNamed(root, PROFILE_COPY.cancel));
    for (const [label, , value] of FIELDS) expect(fieldInput(root, label).value, label).toBe(value);
    expect(heading(root)).toBe(USER.name);
    expect(strings(root).has(SUBTITLE)).toBe(true);
    expect(app.toast).not.toHaveBeenCalled();
  });

  it("WEB_12_profile_save_toasts_profile_saved_and_keeps_the_edit", async () => {
    const app = makeApp();
    const api = spyApi();
    const { root } = await renderProfile(app, api);
    await typeInto(fieldInput(root, "Full name"), "Alexandra Morgan");
    await clickAndSettle(buttonNamed(root, PROFILE_COPY.save));
    expect(app.toast).toHaveBeenCalledTimes(1);
    expect(app.toast).toHaveBeenCalledWith("Profile saved");
    expect(heading(root)).toBe("Alexandra Morgan");
    expect(
      api.setPref,
      "Save makes no server call (it is kept on this device)",
    ).not.toHaveBeenCalled();
  });
});

describe("WEB_12_profile_notifications: channel matrix and quiet hours", () => {
  it("WEB_12_profile_toggling_a_channel_flips_only_that_switch_and_calls_nothing", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await openTab(root, "Notifications");
    const before = matrix(root);
    const sw = switchNamed(root, switchLabel("Spend goes over a limit", "Slack"));
    expect(sw.getAttribute("aria-checked")).toBe("false");
    await clickAndSettle(sw);
    const after = matrix(root);
    expect(after.filter((v, i) => v !== before[i])).toHaveLength(1);
    expect(sw.getAttribute("aria-checked")).toBe("true");
    await clickAndSettle(sw);
    expect(matrix(root)).toEqual(before);
    expect(app.toast).not.toHaveBeenCalled();
    expect(app.setPref, "channels are page state in the design").not.toHaveBeenCalled();
  });

  it("FR_SET_02_WEB_12_profile_decisions_keep_at_least_one_channel_with_the_design_toast", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await openTab(root, "Notifications");
    const [phone, email, slack] = CHANNELS.map((c) =>
      switchNamed(root, switchLabel("A decision needs you", c)),
    ) as [HTMLElement, HTMLElement, HTMLElement];
    await clickAndSettle(phone);
    await clickAndSettle(email);
    expect(app.toast).not.toHaveBeenCalled();
    await clickAndSettle(slack);
    expect(app.toast).toHaveBeenCalledTimes(1);
    expect(app.toast).toHaveBeenCalledWith(NOTIF_COPY.needOne);
    expect(slack.getAttribute("aria-checked"), "the last channel stays on").toBe("true");
    await clickAndSettle(phone);
    expect(phone.getAttribute("aria-checked"), "a channel can come back on").toBe("true");
  });

  it("WEB_12_profile_other_events_may_have_no_channel_at_all", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await openTab(root, "Notifications");
    await clickAndSettle(switchNamed(root, switchLabel("Morning digest at 08:00", "Email")));
    for (const c of CHANNELS) {
      expect(
        switchNamed(root, switchLabel("Morning digest at 08:00", c)).getAttribute("aria-checked"),
      ).toBe("false");
    }
    expect(app.toast).not.toHaveBeenCalled();
  });

  it("FR_SET_02_WEB_12_profile_property_any_toggle_sequence_matches_the_model_and_decisions_never_empty", async () => {
    // Invariant (README: "Decisions must keep at least one channel"): after any sequence of toggles the
    // decisions row has an "on" switch, every other switch is exactly the model's, and the toast fires
    // once per refused toggle and never otherwise.
    await fc.assert(
      fc.asyncProperty(
        fc.array(fc.tuple(fc.integer({ min: 0, max: 4 }), fc.integer({ min: 0, max: 2 })), {
          minLength: 1,
          maxLength: 14,
        }),
        async (steps) => {
          cleanup();
          const app = makeApp();
          const { root } = await renderProfile(app);
          await openTab(root, "Notifications");
          const model = NOTIF.map((n) => [...n[3]]);
          let refused = 0;
          for (const [r, c] of steps) {
            const row = model[r] as boolean[];
            const blocked = r === 0 && row[c] === true && row.filter(Boolean).length === 1;
            if (blocked) refused++;
            else row[c] = !row[c];
            await clickAndSettle(switchNamed(root, matrixLabels[r * 3 + c] ?? ""));
            expect(matrix(root)).toEqual(model.flat().map(String));
            expect(app.toast).toHaveBeenCalledTimes(refused);
          }
          expect(matrix(root).slice(0, 3)).toContain("true");
        },
      ),
      { numRuns: 15 },
    );
  });

  it("WEB_12_profile_quiet_hours_switch_toggles_and_calls_nothing", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await openTab(root, "Notifications");
    const quiet = switchNamed(root, NOTIF_COPY.quietLabel);
    await clickAndSettle(quiet);
    expect(quiet.getAttribute("aria-checked")).toBe("false");
    expect(matrix(root), "the matrix is untouched").toEqual(NOTIF.flatMap((n) => n[3].map(String)));
    await clickAndSettle(quiet);
    expect(quiet.getAttribute("aria-checked")).toBe("true");
    expect(app.toast).not.toHaveBeenCalled();
    expect(app.setPref).not.toHaveBeenCalled();
  });
});

describe("WEB_12_profile_appearance: time and motion go through setPref", () => {
  it("WEB_12_profile_picking_night_calls_setPref_time_night_once", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await openTab(root, "Appearance");
    await clickAndSettle(buttonWith(root, "Lamps and glow"));
    expect(app.setPref).toHaveBeenCalledTimes(1);
    expect(app.setPref).toHaveBeenCalledWith("time", "night");
    expect(app.toast).not.toHaveBeenCalled();
  });

  it("WEB_12_profile_picking_day_on_a_night_app_calls_setPref_time_day", async () => {
    const app = makeApp({ time: "night", night: true });
    const { root } = await renderProfile(app);
    await openTab(root, "Appearance");
    await clickAndSettle(buttonWith(root, "Bright lawns"));
    expect(app.setPref).toHaveBeenCalledWith("time", "day");
  });

  it.each(["Lively", "Calm", "Still"])(
    "WEB_12_profile_picking_motion_%s_calls_setPref_motion",
    async (label) => {
      const app = makeApp({ motion: label === "Lively" ? "calm" : "lively" });
      const { root } = await renderProfile(app);
      await openTab(root, "Appearance");
      await clickAndSettle(buttonNamed(root, label));
      expect(app.setPref).toHaveBeenCalledTimes(1);
      expect(app.setPref).toHaveBeenCalledWith("motion", label.toLowerCase());
    },
  );

  it("WEB_12_profile_the_choice_follows_the_app_not_the_click", async () => {
    // The shell owns time and motion: pressed state and help text come from the AppCtx props.
    const app = makeApp();
    const { m, root } = await renderProfile(app);
    await openTab(root, "Appearance");
    await clickAndSettle(buttonNamed(root, "Still"));
    expect(pressedOf(buttonNamed(root, "Still")), "no local copy of the pref").toBe("false");
    m.render(profileTree(makeApp({ motion: "still", time: "night", night: true })));
    await settle();
    expect(pressedOf(buttonNamed(root, "Still"))).toBe("true");
    expect(pressedOf(buttonWith(root, "Lamps and glow"))).toBe("true");
    expect(strings(root).has(APPEARANCE_COPY.help.still)).toBe(true);
  });

  it("WEB_12_profile_an_unknown_motion_value_reads_as_calm_the_default_not_lively", async () => {
    const { root } = await renderProfile(makeApp({ motion: "wild" as never }));
    await openTab(root, "Appearance");
    expect(pressedOf(buttonNamed(root, "Calm"))).toBe("true");
    expect(pressedOf(buttonNamed(root, "Lively"))).toBe("false");
    expect(strings(root).has(APPEARANCE_COPY.help.calm)).toBe(true);
  });
});

describe("WEB_12_profile_security: actions and sessions", () => {
  it.each(SECURITY_COPY.rows.map((r) => [r[2], r[3]] as const))(
    "WEB_12_profile_security_%s_button_toasts_%j",
    async (action, message) => {
      const app = makeApp();
      const { root } = await renderProfile(app);
      await openTab(root, "Security");
      await clickAndSettle(buttonNamed(root, action));
      expect(app.toast).toHaveBeenCalledTimes(1);
      expect(app.toast).toHaveBeenCalledWith(message);
      expect(app.go).not.toHaveBeenCalled();
    },
  );

  it("WEB_12_profile_signing_out_one_device_toasts_its_name_and_removes_the_row", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await openTab(root, "Security");
    await clickAndSettle(signOutButtons(root)[0] as Element);
    expect(app.toast).toHaveBeenLastCalledWith("Signed out of iPhone 15 · Tilo app");
    expect(strings(root).has(SESSIONS[1][0])).toBe(false);
    expect(strings(root).has(SESSIONS[1][1])).toBe(false);
    expect(signOutButtons(root)).toHaveLength(1);
    await clickAndSettle(signOutButtons(root)[0] as Element);
    expect(app.toast).toHaveBeenLastCalledWith("Signed out of iPad · Safari");
    expect(signOutButtons(root)).toHaveLength(0);
    expect(strings(root).has(SESSIONS[0][0]), "this device stays").toBe(true);
    expect(strings(root).has(SECURITY_COPY.thisDevice)).toBe(true);
    expect(app.toast).toHaveBeenCalledTimes(2);
  });

  it("WEB_12_profile_sign_out_everywhere_else_keeps_only_this_device", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await openTab(root, "Security");
    await clickAndSettle(buttonNamed(root, SECURITY_COPY.everywhere));
    expect(app.toast).toHaveBeenCalledTimes(1);
    expect(app.toast).toHaveBeenCalledWith(SECURITY_COPY.everywhereToast);
    expect(strings(root).has(SESSIONS[1][0]) || strings(root).has(SESSIONS[2][0])).toBe(false);
    expect(strings(root).has(SESSIONS[0][0])).toBe(true);
    expect(signOutButtons(root)).toHaveLength(0);
    expect(buttonNamed(root, SECURITY_COPY.everywhere), "the link stays").toBeDefined();
  });
});

describe("WEB_12_profile_billing: toasts and the Ledger link", () => {
  it("WEB_12_profile_compare_plans_and_update_card_toast_their_lines", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await openTab(root, "Plan and billing");
    await clickAndSettle(buttonNamed(root, BILLING_COPY.compare));
    expect(app.toast).toHaveBeenLastCalledWith(BILLING_COPY.compareToast);
    await clickAndSettle(buttonNamed(root, BILLING_COPY.update));
    expect(app.toast).toHaveBeenLastCalledWith(BILLING_COPY.updateToast);
    expect(app.toast).toHaveBeenCalledTimes(2);
  });

  it("WEB_12_profile_each_invoice_download_toasts_its_month", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await openTab(root, "Plan and billing");
    const downloads = [
      ...region(root, "Plan and billing").querySelectorAll('button[aria-label="Download"]'),
    ];
    expect(downloads).toHaveLength(INVOICES.length);
    for (const [i, d] of downloads.entries()) {
      await clickAndSettle(d);
      expect(app.toast).toHaveBeenLastCalledWith(`Downloaded ${INVOICES[i]?.[2]} invoice`);
    }
    expect(app.toast).toHaveBeenCalledTimes(INVOICES.length);
  });

  it("WEB_12_profile_the_agent_spend_card_goes_to_the_ledger_without_params", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await openTab(root, "Plan and billing");
    await clickAndSettle(buttonWith(root, BILLING_COPY.openLedger));
    expect(app.go).toHaveBeenCalledTimes(1);
    expect(app.go.mock.calls[0]?.[0]).toBe("ledger");
    expect(app.go.mock.calls[0]?.[1] ?? {}).toEqual({});
  });
});

describe("WEB_12_profile_nothing: no approve control, no new work", () => {
  it("WEB_12_profile_nothing_on_the_page_approves_or_starts_work_and_every_toast_is_one_string", async () => {
    const app = makeApp();
    const api = spyApi();
    const { root } = await renderProfile(app, api);
    await typeInto(fieldInput(root, "Full name"), "Alexandra Morgan");
    await clickAndSettle(buttonNamed(root, PROFILE_COPY.save));
    await openTab(root, "Notifications");
    for (const l of matrixLabels) await clickAndSettle(switchNamed(root, l));
    await openTab(root, "Security");
    await clickAndSettle(buttonNamed(root, SECURITY_COPY.everywhere));
    await openTab(root, "Plan and billing");
    await clickAndSettle(buttonNamed(root, BILLING_COPY.compare));
    expect(app.decide).not.toHaveBeenCalled();
    expect(app.addWorld).not.toHaveBeenCalled();
    expect(app.setPref).not.toHaveBeenCalled();
    expect(api.decide).not.toHaveBeenCalled();
    expect(app.toast.mock.calls.every((c) => c.length === 1 && typeof c[0] === "string")).toBe(
      true,
    );
  });
});
