import { beforeEach, expect, it, vi } from "vitest";
import type { AuthState } from "../auth/auth";

const auth = vi.hoisted(() => ({
  state: { status: "google", displayName: "Ada Test", email: "ada@example.test" } as AuthState,
}));
vi.mock("../auth/session", () => ({ session: { getState: () => auth.state } }));

beforeEach(() => {
  vi.resetModules();
  auth.state = { status: "google", displayName: "Ada Test", email: "ada@example.test" };
});

async function setup(status: number) {
  const { HttpClient, TiloApiError } = await import("./http");
  let founded = false;
  const fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("/v1/people/first")) {
      founded = status === 201;
      return new Response("{}", { status });
    }
    return new Response(
      founded ? '{"rows":[],"parked":[],"truncated":false,"as_of":"2026-10-14T08:00:00Z"}' : "{}",
      { status: founded ? 200 : 404 },
    );
  });
  const client = () => new HttpClient({ baseUrl: "https://api.test", fetch });
  return { client, fetch, TiloApiError };
}

it("W-FOUND-1 FR-PPL founder 201 rereads plate and uses only sign-in profile fields", async () => {
  const { client, fetch } = await setup(201);
  await expect(client().getJson("/v1/plate")).resolves.toMatchObject({ rows: [] });
  const post = fetch.mock.calls.find(([url]) => String(url).endsWith("/v1/people/first"));
  expect(post?.[1]?.method).toBe("POST");
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({
    display_name: "Ada Test",
    email: "ada@example.test",
    aliases: [],
    time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    preferred_channel: "web",
  });
  expect(fetch).toHaveBeenCalledTimes(3);
});

it("W-FOUND-1 FR-PPL founder 403 stays honest 404 with one attempt across concurrent clients and later reads", async () => {
  const { client, fetch, TiloApiError } = await setup(403);
  const reads = await Promise.allSettled([
    client().getJson("/v1/plate"),
    client().getJson("/v1/plate"),
  ]);
  for (const read of reads) {
    expect(read.status).toBe("rejected");
    if (read.status === "rejected") {
      expect(read.reason).toBeInstanceOf(TiloApiError);
      expect(read.reason.status).toBe(404);
    }
  }
  await expect(client().getJson("/v1/plate")).rejects.toMatchObject({ status: 404 });
  expect(fetch.mock.calls.filter(([url]) => String(url).endsWith("/v1/people/first"))).toHaveLength(
    1,
  );
});

it.each(["anonymous", "signed_out", "unknown"] as const)(
  "W-FOUND-1 FR-PPL %s sessions never bootstrap",
  async (status) => {
    auth.state = { status };
    const { client, fetch } = await setup(201);
    await expect(client().getJson("/v1/plate")).rejects.toMatchObject({ status: 404 });
    expect(fetch).toHaveBeenCalledTimes(1);
  },
);

it("W-FOUND-1 FR-PPL uncertain founding failure is surfaced and never resubmitted", async () => {
  const { client, fetch } = await setup(503);
  await expect(client().getJson("/v1/plate")).rejects.toMatchObject({ status: 503, write: true });
  await expect(client().getJson("/v1/plate")).rejects.toMatchObject({ status: 503 });
  expect(fetch.mock.calls.filter(([url]) => String(url).endsWith("/v1/people/first"))).toHaveLength(
    1,
  );
});
