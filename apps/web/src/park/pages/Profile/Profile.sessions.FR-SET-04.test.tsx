// @vitest-environment happy-dom
// FR-SET-04 page behaviour: per-session sign out has an accessible name with the device, and the bulk
// action asks for an in-page confirmation first. Sample data only; nothing is sent anywhere.
import { afterEach, describe, expect, it } from "vitest";
import { makeApp } from "../../../../test-support/park/profileApp";
import { SESSIONS } from "../../../../test-support/park/profileExpect";
import {
  buttonNamed,
  cleanup,
  clickAndSettle,
  openTab,
  region,
  renderProfile,
  strings,
} from "./testApp";

afterEach(cleanup);
const EVERYWHERE = "Sign out everywhere else";
const names = (root: ParentNode): string[] =>
  [...root.querySelectorAll("button")].map((b) => b.getAttribute("aria-label") ?? "");

describe("FR_SET_04 security sessions", () => {
  it("FR_SET_04_each_other_session_has_a_sign_out_button_named_with_its_device", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Security");
    expect(names(root)).toContain(`Sign out ${SESSIONS[1][0]}`);
    expect(names(root)).toContain(`Sign out ${SESSIONS[2][0]}`);
    expect(names(root)).not.toContain(`Sign out ${SESSIONS[0][0]}`);
  });

  it("FR_SET_04_bulk_sign_out_asks_first_and_cancel_changes_nothing", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await openTab(root, "Security");
    await clickAndSettle(buttonNamed(root, EVERYWHERE));
    const box = region(root, "Confirm sign out of other sessions");
    expect(box.textContent).toContain("2");
    expect(app.toast).not.toHaveBeenCalled();
    await clickAndSettle(buttonNamed(box, "Cancel"));
    expect(root.querySelector('[aria-label="Confirm sign out of other sessions"]')).toBeNull();
    expect(strings(root).has(SESSIONS[1][0])).toBe(true);
    expect(app.toast).not.toHaveBeenCalled();
  });

  it("FR_SET_04_confirming_signs_out_every_session_except_this_one", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await openTab(root, "Security");
    await clickAndSettle(buttonNamed(root, EVERYWHERE));
    const box = region(root, "Confirm sign out of other sessions");
    await clickAndSettle(buttonNamed(box, "Sign out the other sessions"));
    expect(strings(root).has(SESSIONS[1][0]) || strings(root).has(SESSIONS[2][0])).toBe(false);
    expect(strings(root).has(SESSIONS[0][0])).toBe(true);
    expect(app.toast).toHaveBeenCalledWith("Signed out everywhere except this device");
  });

  it("FR_SET_04_bulk_sign_out_is_hidden_when_there_is_no_other_session", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Security");
    await clickAndSettle(buttonNamed(root, EVERYWHERE));
    await clickAndSettle(
      buttonNamed(
        region(root, "Confirm sign out of other sessions"),
        "Sign out the other sessions",
      ),
    );
    await clickAndSettle(buttonNamed(root, EVERYWHERE));
    expect(root.querySelector('[aria-label="Confirm sign out of other sessions"]')).toBeNull();
  });
});
