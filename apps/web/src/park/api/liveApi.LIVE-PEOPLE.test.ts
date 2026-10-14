import { expect, it, vi } from "vitest";
import { createLiveApi } from "./liveApi";
vi.mock("../../auth/session", () => ({ session: { getState: () => ({ status: "signed_out" }) } }));
it("LIVE-PEOPLE FR-TEAM-01 absent person is setup, not an empty directory", async () => {
  const api = createLiveApi({
    baseUrl: "https://setup.test",
    fetch: vi.fn(async () => new Response("{}", { status: 404 })),
  });
  await expect(api.getTeam()).resolves.toMatchObject({
    source: "live",
    data: { setupRequired: true, people: [] },
  });
  await expect(api.getAgenda()).resolves.toMatchObject({
    source: "live",
    data: { setupRequired: true },
  });
});

it("LIVE-PEOPLE FR-TEAM-01 service failures remain errors", async () => {
  const api = createLiveApi({
    baseUrl: "https://failure.test",
    fetch: vi.fn(async () => new Response("{}", { status: 503 })),
  });
  await expect(api.getTeam()).rejects.toMatchObject({ status: 503 });
  await expect(api.getAgenda()).rejects.toMatchObject({ status: 503 });
});
