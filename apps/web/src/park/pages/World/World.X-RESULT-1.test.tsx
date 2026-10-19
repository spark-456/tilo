// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click } from "../../../../test-support/park/componentsHarness";
import {
  control,
  liveWorldsApi,
  mountWorld,
  settle,
} from "../../../../test-support/park/worldHarness";
import { HttpClient } from "../../../api/http";
import { createLiveApi } from "../../api/liveApi";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("X_RESULT_1_binary_download_uses_auth_and_app_check", async () => {
  const fetcher = vi.fn(
    async (_url: string | URL | Request, _init?: RequestInit) =>
      new Response("Replay report", { headers: { "content-type": "text/plain" } }),
  );
  const http = new HttpClient({
    baseUrl: "https://api.example.test",
    fetch: fetcher,
    authToken: async () => "fake-id",
    appCheckToken: async () => "fake-app-check",
  });
  const blob = await http.getBlob("/worlds/w_result/result");
  expect(await blob.text()).toBe("Replay report");
  const headers = new Headers(fetcher.mock.calls[0]?.[1]?.headers);
  expect(headers.get("Authorization")).toBe("Bearer fake-id");
  expect(headers.get("X-Firebase-AppCheck")).toBe("fake-app-check");
});

it("X_RESULT_1_Park_Open_result_fetches_owner_route_and_downloads", async () => {
  const fetcher = vi.fn(
    async (_url: string | URL | Request, _init?: RequestInit) =>
      new Response("Replay report", { headers: { "content-type": "text/plain" } }),
  );
  const api = Object.assign(
    createLiveApi({ baseUrl: "https://api.example.test", fetch: fetcher }),
    liveWorldsApi(),
  );
  const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:result");
  const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  const anchor = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  const rig = await mountWorld({ id: "comp", api });
  create.mockClear(); // World art also creates blob URLs during mounting; count only the download action.
  revoke.mockClear();
  anchor.mockClear();
  const button = control(rig.el, "Open result");
  expect(button.getAttribute("aria-disabled")).not.toBe("true");
  click(button);
  await settle();
  expect(fetcher.mock.calls[0]?.[0]).toBe("https://api.example.test/worlds/comp/result");
  expect(create).toHaveBeenCalledOnce();
  expect(anchor).toHaveBeenCalledOnce();
  expect(revoke).toHaveBeenCalledWith("blob:result");
});
