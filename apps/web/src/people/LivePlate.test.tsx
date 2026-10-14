// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, mount, q } from "../../test-support/park/componentsHarness";
import { ClientProvider } from "../api/ClientProvider";
import { HttpClient } from "../api/http";
import { S_27 } from "../screens/S_27";

afterEach(cleanup);
it("PE_26 W2 missing person plate is empty without an error or invented timestamp", async () => {
  const root = await screen(async () => new Response('{"detail":"Not Found"}', { status: 404 }));
  expect(root.textContent).toContain("Nothing on your plate yet");
  expect(root.textContent).not.toMatch(/Could not load|As of|sample|venue shortlist/i);
  expect(root.querySelector('[role="alert"]')).toBeNull();
  expect(root.querySelectorAll("button")).toHaveLength(0);
});
const body = {
  as_of: "2026-10-09T12:00:00Z",
  truncated: true,
  rows: [
    {
      ref: { kind: "work_item", id: "wi_live" },
      group: "attention",
      title: "Actual task",
      due: null,
      at: null,
    },
  ],
  parked: [],
};
async function screen(fetch: typeof globalThis.fetch) {
  const client = new HttpClient({ baseUrl: "https://api.test", fetch });
  const m = mount(
    <ClientProvider client={client}>
      <S_27 />
    </ClientProvider>,
  );
  await act(async () => {
    for (let i = 0; i < 50; i++) await Promise.resolve();
  });
  return m.container;
}
it("FR_PA_02_03 server failures leave live My plate unavailable without fixture fallback", async () => {
  const root = await screen(async () => new Response("{}", { status: 503 }));
  expect(root.textContent).toContain("Could not load your plate");
  expect(root.textContent).not.toMatch(/Actual task|sample data|venue shortlist/i);
});
it("FR_PA_02_03 live My plate reads only the live plate and never shows preview data or simulated writes", async () => {
  const fetch = vi.fn(async (_url: RequestInfo | URL) => new Response(JSON.stringify(body)));
  const root = await screen(fetch);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0]?.[0]).toBe("https://api.test/v1/plate");
  expect(root.textContent).toContain("Actual task");
  expect(root.textContent).toContain("Needs attention");
  expect(root.textContent).toContain("More items are available than this view can show");
  expect(root.textContent).not.toMatch(/sample data|Preview|Priya|venue shortlist/i);
  expect(root.querySelectorAll("button")).toHaveLength(0);
});
it("FR_PA_02_03 failed and unreadable replies stay unavailable until an explicit retry succeeds", async () => {
  let reply: unknown = {};
  const fetch = vi.fn(async () => new Response(JSON.stringify(reply)));
  const root = await screen(fetch);
  expect(root.textContent).toContain("Could not load your plate");
  expect(root.textContent).not.toMatch(/Actual task|venue shortlist/i);
  reply = { ...body, truncated: false, rows: [] };
  click(q(root, "button"));
  await act(async () => {
    for (let i = 0; i < 50; i++) await Promise.resolve();
  });
  expect(root.textContent).toContain("Nothing on your plate yet");
  expect(fetch).toHaveBeenCalledTimes(2);
});
