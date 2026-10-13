// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../test-support/park/componentsHarness";
import { ClientProvider } from "../api/ClientProvider";
import { HttpClient } from "../api/http";
import { peopleListsApi } from "../park/api/liveApi";
import { S_26 } from "../screens/S_26";
import { S_28 } from "../screens/S_28";

vi.mock("../api/ClientProvider", async (original) => ({
  ...(await original<typeof import("../api/ClientProvider")>()),
  API_URL: "https://api.test",
  authToken: async () => "fake.token.value",
  appCheckToken: async () => null,
}));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const envelope = (id: string, title: string) => ({
  items: [
    {
      id,
      title,
      status: "active",
      created_at: "2026-10-12T00:00:00Z",
      body: null,
      scope: { kind: "personal", user: "u_self" },
    },
  ],
  truncated: false,
});
async function settle() {
  await act(async () => {
    for (let n = 0; n < 60; n++) await Promise.resolve();
  });
}

it("HR_1 FR_MTG_10 FR_PB_01 live lists fetch recorded data without fixtures or writes", async () => {
  const fetch = vi.fn(
    async (url: RequestInfo | URL) =>
      new Response(
        JSON.stringify(
          String(url).endsWith("/meetings")
            ? {
                items: [
                  {
                    id: "mt_actual",
                    title: "Recorded meeting",
                    status: "scheduled",
                    created_at: "2026-10-12T00:00:00Z",
                    scheduled: null,
                  },
                ],
                truncated: true,
              }
            : envelope("pb_actual", "Recorded pin"),
        ),
      ),
  );
  vi.stubGlobal("fetch", fetch);
  for (const screen of [<S_26 key="meeting" params={[]} />, <S_28 key="pins" />]) {
    const m = mount(
      <ClientProvider client={new HttpClient({ baseUrl: "https://api.test" })}>
        {screen}
      </ClientProvider>,
    );
    expect(m.container.textContent).toContain("Loading");
    await settle();
    expect(m.container.textContent).toContain("Recorded");
    expect(m.container.textContent).not.toMatch(/sample data|Preview|Priya|venue shortlist/i);
    expect(m.container.querySelectorAll("button")).toHaveLength(0);
    m.unmount();
  }
  expect(fetch.mock.calls.map((c) => c[0])).toEqual([
    "https://api.test/v1/meetings",
    "https://api.test/v1/pinboards",
  ]);
});

it("HR_1 FR_PB_01 failed live read retries explicitly and an empty reply stays empty", async () => {
  let failed = true;
  const fetch = vi.fn(async () =>
    failed
      ? new Response("{}", { status: 503 })
      : new Response(JSON.stringify({ items: [], truncated: false })),
  );
  vi.stubGlobal("fetch", fetch);
  const m = mount(
    <ClientProvider client={new HttpClient({ baseUrl: "https://api.test" })}>
      <S_28 />
    </ClientProvider>,
  );
  await settle();
  expect(m.container.textContent).toContain("Could not load");
  failed = false;
  click(m.container.querySelector("button") as HTMLButtonElement);
  await settle();
  expect(m.container.textContent).toContain("No pinboard items yet");
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("HR_1 FR_MTG_10 FR_PB_01 malformed rows refuse the entire reply", async () => {
  const client = new HttpClient({
    baseUrl: "https://api.test",
    fetch: async () => new Response(JSON.stringify(envelope("wrong_id", "bad"))),
  });
  const api = peopleListsApi(client);
  await expect(api.getMeetings()).rejects.toThrow();
  await expect(api.getPinboards()).rejects.toThrow();
});
