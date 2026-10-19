import { describe, expect, it, vi } from "vitest";
import { TiloApiError } from "../../api/http";
import { NotBuilt, createLiveApi } from "./liveApi";

const item = {
  id: "e:one",
  kind: "done",
  created_at: "2026-10-09T10:00:00Z",
  world_id: "world-one",
  title: "An item is ready",
  card_id: null,
  artifact_id: "art_one",
};
const apiFor = (body: unknown, status = 200) => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
  return { api: createLiveApi({ baseUrl: "https://api.example.test/", fetch: fetcher }), fetcher };
};

describe("FR_UX_11 live notifications", () => {
  it("FR_UX_11_maps_only_served_words_time_and_world_without_sample_details", async () => {
    const { api, fetcher } = apiFor({ notifications: [item], count: 1 });
    expect(await api.getNotifications()).toEqual({
      source: "live",
      data: [
        {
          id: item.id,
          kind: "done",
          title: item.title,
          t: item.created_at,
          sub: "",
          go: ["world", item.world_id],
        },
      ],
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0]?.[0]).toBe("https://api.example.test/v1/notifications?limit=100");
  });
  it("FR_UX_11_links_needs_items_to_the_same_decision_key", async () => {
    const { api } = apiFor({
      notifications: [{ ...item, kind: "needs", card_id: "card-one" }],
      count: 1,
    });
    expect((await api.getNotifications()).data[0]?.dec).toBe("world-one:card-one");
  });
  it("FR_UX_11_empty_bell_is_real_empty_data", async () => {
    expect(await apiFor({ notifications: [], count: 0 }).api.getNotifications()).toEqual({
      data: [],
      source: "live",
    });
  });
  it.each([
    null,
    {},
    { notifications: [null], count: 1 },
    { notifications: [{ ...item, kind: "unknown" }], count: 1 },
    { notifications: [{ ...item, world_id: null }], count: 1 },
    { notifications: [{ ...item, created_at: "" }], count: 1 },
  ])("FR_UX_11_unreadable_body_is_an_error_%j", async (body) => {
    await expect(apiFor(body).api.getNotifications()).rejects.toBeInstanceOf(TiloApiError);
  });
  it("FR_UX_11_transport_failure_does_not_resolve_as_empty", async () => {
    await expect(
      apiFor({ detail: "unavailable" }, 503).api.getNotifications(),
    ).rejects.toMatchObject({ status: 503 });
  });
  it("FR_UX_11_without_base_remains_unbuilt", async () => {
    await expect(createLiveApi().getNotifications()).rejects.toBeInstanceOf(NotBuilt);
  });
});
