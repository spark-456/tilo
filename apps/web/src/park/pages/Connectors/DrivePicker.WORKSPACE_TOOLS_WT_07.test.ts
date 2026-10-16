// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import { type PickerRuntime, openDrivePicker, pickerConfig } from "./DrivePicker";

const config = {
  clientId: "client.apps.googleusercontent.com",
  apiKey: "public-browser-key",
  projectNumber: "123456789",
};

function fakeRuntime() {
  let tokenCallback:
    | ((response: { access_token?: string; error?: string; scope?: string }) => void)
    | undefined;
  let pickerCallback: ((data: { action: string; docs?: unknown[] }) => void) | undefined;
  const requestAccessToken = vi.fn();
  const setOAuthToken = vi.fn();
  const setVisible = vi.fn();
  const builder = {
    addView: vi.fn().mockReturnThis(),
    setOAuthToken: setOAuthToken.mockReturnThis(),
    setDeveloperKey: vi.fn().mockReturnThis(),
    setAppId: vi.fn().mockReturnThis(),
    setCallback: vi.fn((callback) => {
      pickerCallback = callback;
      return builder;
    }),
    build: vi.fn(() => ({ setVisible })),
  };
  const runtime: PickerRuntime = {
    oauth2: {
      initTokenClient: vi.fn(({ callback }) => {
        tokenCallback = callback;
        return { requestAccessToken };
      }),
    },
    picker: {
      PickerBuilder: vi.fn(() => builder),
      DocsView: vi.fn(() => ({ setMode: vi.fn() })),
      DocsViewMode: { LIST: "list" },
      ViewId: { DOCS: "docs" },
      Action: { PICKED: "picked", CANCEL: "cancel" },
    },
  };
  return {
    runtime,
    requestAccessToken,
    setOAuthToken,
    setVisible,
    builder,
    token: (response: { access_token?: string; error?: string; scope?: string }) =>
      tokenCallback?.(response),
    pick: (data: { action: string; docs?: unknown[] }) => pickerCallback?.(data),
  };
}

describe("WORKSPACE_TOOLS_WT_07_Drive_Picker", () => {
  it("WORKSPACE_TOOLS_WT_07_missing_console_values_leave_the_picker_not_set_up", () => {
    expect(pickerConfig({})).toBeNull();
    expect(
      pickerConfig({
        VITE_GOOGLE_PICKER_CLIENT_ID: config.clientId,
        VITE_GOOGLE_PICKER_API_KEY: config.apiKey,
      }),
    ).toBeNull();
    expect(
      pickerConfig({
        VITE_GOOGLE_PICKER_CLIENT_ID: config.clientId,
        VITE_GOOGLE_PICKER_API_KEY: config.apiKey,
        VITE_GOOGLE_PICKER_PROJECT_NUMBER: config.projectNumber,
      }),
    ).toEqual(config);
  });

  it("WORKSPACE_TOOLS_WT_07_requests_drive_file_only_and_hands_the_token_only_to_Picker", async () => {
    const fake = fakeRuntime();
    const result = openDrivePicker(config, async () => fake.runtime);
    await Promise.resolve();
    expect(fake.runtime.oauth2.initTokenClient).toHaveBeenCalledWith(
      expect.objectContaining({
        client_id: config.clientId,
        scope: "https://www.googleapis.com/auth/drive.file",
        include_granted_scopes: false,
      }),
    );
    expect(fake.requestAccessToken).toHaveBeenCalledWith({ prompt: "select_account" });
    fake.token({
      access_token: "memory-only-token",
      scope: "https://www.googleapis.com/auth/drive.file",
    });
    expect(fake.setOAuthToken).toHaveBeenCalledWith("memory-only-token");
    expect(fake.builder.setAppId).toHaveBeenCalledWith(config.projectNumber);
    expect(fake.builder.setDeveloperKey).toHaveBeenCalledWith(config.apiKey);
    expect(fake.setVisible).toHaveBeenCalledWith(true);
    fake.pick({ action: "picked", docs: [{ id: "file1" }] });
    expect(await result).toBe("picked");
  });

  it("WORKSPACE_TOOLS_WT_07_cancel_or_missing_scope_never_claims_a_pick", async () => {
    const fake = fakeRuntime();
    const cancelled = openDrivePicker(config, async () => fake.runtime);
    await Promise.resolve();
    fake.token({
      access_token: "short-lived",
      scope: "https://www.googleapis.com/auth/drive.file",
    });
    fake.pick({ action: "cancel" });
    expect(await cancelled).toBe("cancelled");

    const denied = openDrivePicker(config, async () => fake.runtime);
    await Promise.resolve();
    fake.token({
      access_token: "wrong-scope",
      scope: "https://www.googleapis.com/auth/drive.readonly",
    });
    await expect(denied).rejects.toThrow("Drive access was not granted");
  });
});
