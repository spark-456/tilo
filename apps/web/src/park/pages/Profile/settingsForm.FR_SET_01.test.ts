// FR-SET-01 (ADR-0039): the form text and the contract's profile are two views of one value. What is shown can be
// read back unchanged, so a save never rewrites a field the person did not touch.
import type { UserSettingsWeekday } from "@tilo/contracts";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { userSettings } from "../../api/fixtures";
import { baseForm, formOf, problemOf, profileOf } from "./settingsForm";

const DAYS: UserSettingsWeekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const clock = fc
  .tuple(fc.integer({ min: 0, max: 23 }), fc.integer({ min: 0, max: 59 }))
  .map(([h, m]) => `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`);

describe("FR_SET_01_settings_form", () => {
  it("test_FR_SET_01_property_any_profile_reads_back_from_its_form_unchanged", () => {
    const days = fc.subarray(DAYS, { minLength: 1 }) as fc.Arbitrary<
      [UserSettingsWeekday, ...UserSettingsWeekday[]]
    >;
    const title = fc.option(fc.stringMatching(/^[A-Za-z][A-Za-z ]{0,20}[A-Za-z]$/), { nil: null });
    fc.assert(
      fc.property(
        days,
        clock,
        clock,
        title,
        fc.constantFrom("en", "en-GB", "fr-FR"),
        (d, start, end, t, language) => {
          const p = {
            ...userSettings.profile,
            title: t,
            language,
            working_hours: { days: d, start, end },
          };
          expect(profileOf(formOf(p))).toEqual(p);
        },
      ),
    );
  });

  it("test_FR_SET_01_the_design_text_for_hours_and_language_is_what_is_shown_and_read", () => {
    const f = formOf(userSettings.profile);
    expect(f.hours).toBe("08:30 – 17:30, Monday to Friday");
    expect(f.lang).toBe("English (UK)");
    expect(profileOf({ ...f, hours: "09:00 - 12:00, Mon, Wed and Fri" })?.working_hours).toEqual({
      days: ["mon", "wed", "fri"],
      start: "09:00",
      end: "12:00",
    });
    expect(profileOf({ ...f, hours: "9 to 5" })).toBeNull();
    expect(profileOf({ ...f, hours: "08:30 – 17:30, Someday" })).toBeNull();
  });

  it("test_FR_SET_01_a_version_zero_document_starts_from_the_signed_in_identity_only", () => {
    const who = { name: "Ana Silva", email: "ana@example.test", tz: "" };
    expect(baseForm({ ...userSettings, version: 0 }, who).name).toBe("Ana Silva");
    expect(baseForm({ ...userSettings, version: 0 }, who).tz).toBe("Europe/London");
    expect(baseForm(userSettings, who).name).toBe("Alex Morgan");
  });

  it("test_FR_SET_01_problems_never_claim_a_save_and_a_server_text_is_not_trusted_as_markup", () => {
    expect(problemOf({ status: 401 }, true)).toMatch(/Nothing was saved/);
    expect(problemOf({ name: "NotBuilt" }, false)).toMatch(/not connected/);
    expect(problemOf(new Error("<b>x</b>"), true)).not.toContain("<b>");
  });
});
