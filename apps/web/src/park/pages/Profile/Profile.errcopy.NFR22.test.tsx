// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { makeApp } from "../../../../test-support/park/profileApp";
import { TiloApiError, displayApiError } from "../../../api/http";
import { createFixtureApi } from "../../api/fixtureApi";
import {
  buttonNamed,
  cleanup,
  clickAndSettle,
  fieldInput,
  renderProfile,
  settle,
  spyApi,
  text,
  typeInto,
  withFakeSettings,
} from "./testApp";

afterEach(cleanup);
const failure = () =>
  new TiloApiError("private backend detail", 503, true, true, "store_unavailable");

it.each(["getUser", "getProfileSettings", "getLedger"] as const)(
  "NFR22 FR_SET_01 Profile %s failure maps safely and retries only reads",
  async (method) => {
    const base = createFixtureApi();
    const read = vi.fn(base[method]).mockRejectedValueOnce(failure());
    const api = spyApi({ ...base, [method]: read });
    const { root } = await renderProfile(makeApp(), api);
    const heading = root.querySelector("h1");
    expect(text(root.querySelector('[role="alert"]'))).toContain(displayApiError(failure()));
    expect(text(root)).not.toContain("private backend detail");
    await clickAndSettle(buttonNamed(root, "Retry"));
    expect(read).toHaveBeenCalledTimes(2);
    expect(root.querySelector("h1")).toBe(heading);
    expect(fieldInput(root, "Full name").value).toBe("Alex Morgan");
    expect(api.saveUserSettings).not.toHaveBeenCalled();
  },
);

it("TILO_T_STATES_HR1_FR_SET_01_settings_use_shared_loading_and_error_states", async () => {
  const base = createFixtureApi();
  let reject: (e: unknown) => void = () => {};
  const held = new Promise<never>((_, fail) => {
    reject = fail;
  });
  const api = spyApi({
    ...base,
    getUserSettings: vi.fn(base.getUserSettings).mockReturnValueOnce(held),
  });
  const { root } = await renderProfile(makeApp(), api);
  const box = root.querySelector<HTMLElement>("[data-profile-settings-state]");
  expect(box).not.toBeNull();
  expect(box?.style.blockSize).toBe("176px");
  expect(box?.querySelector('[data-testid="tt-loading"]')?.getAttribute("aria-busy")).toBe("true");
  expect(root.querySelector("input")).toBeNull();
  await act(async () => reject(failure()));
  await settle();
  expect(root.querySelector("[data-profile-settings-state]")).toBe(box);
  expect(box?.querySelector('[data-testid="tt-error"]')?.getAttribute("role")).toBe("alert");
  expect(text(root.querySelector('[role="alert"] h2'))).toBe(displayApiError(failure()));
  await clickAndSettle(buttonNamed(root, "Try again"));
  expect(api.getUserSettings).toHaveBeenCalledTimes(2);
  expect(api.saveUserSettings).not.toHaveBeenCalled();
});

it("NFR22 FR_SET_01 uncertain save Retry refreshes without repeating the PUT or losing draft edits", async () => {
  const base = withFakeSettings().api;
  const failed = new TiloApiError("private write detail", null, false, true, "write_unconfirmed");
  const api = spyApi({ ...base, saveUserSettings: vi.fn().mockRejectedValue(failed) });
  const app = makeApp();
  const { root } = await renderProfile(app, api);
  await typeInto(fieldInput(root, "Full name"), "Ada Lovelace");
  await clickAndSettle(buttonNamed(root, "Save changes"));
  expect(text(root.querySelector('[role="alert"]'))).toContain(displayApiError(failed));
  expect(text(root)).not.toContain("private write detail");
  expect(text(root)).not.toContain("Nothing was saved");
  await clickAndSettle(buttonNamed(root, "Retry"));
  expect(api.getUserSettings).toHaveBeenCalledTimes(2);
  expect(api.saveUserSettings).toHaveBeenCalledTimes(1);
  expect(fieldInput(root, "Full name").value).toBe("Ada Lovelace");
  expect(app.toast).not.toHaveBeenCalled();
});
