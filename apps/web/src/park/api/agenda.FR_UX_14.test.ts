import { describe, expect, it, vi } from "vitest";
import { TiloApiError } from "../../api/http";
import { NotBuilt, createLiveApi } from "./liveApi";

const plate = {
  v: "1.0",
  user: "person-a",
  as_of: "2026-10-09T03:00:00Z",
  today: "2026-10-09",
  rows: [
    {
      ref: { kind: "calendar_entry", id: "entry-a" },
      title: "Design review",
      at: "2026-10-09T05:00:00Z",
      due: null,
      from: null,
      group: "soon",
    },
    {
      ref: { kind: "pin", id: "pin-a" },
      title: "Prepare notes",
      at: null,
      due: "2026-10-10",
      from: "person-b",
      group: "soon",
    },
  ],
  parked: [],
  truncated: false,
};
const apiFor = (body: unknown, status = 200) => {
  const fetch = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify(body), { status }),
  );
  return { api: createLiveApi({ baseUrl: "https://api.example.test", fetch }), fetch };
};
describe("FR_UX_14 FR_PB live Agenda", () => {
  it("PE_26 W2 a missing person plate is empty live work with no invented date", async () => {
    const { api, fetch } = apiFor({ detail: "Not Found" }, 404);
    expect(await api.getAgenda()).toMatchObject({
      source: "live",
      data: {
        events: null,
        plate: { today: null, asOf: null, rows: [], parked: [], truncated: false },
      },
    });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("FR_UX_14 reads the plate without inventing events, end times or people", async () => {
    const { api, fetch } = apiFor(plate);
    const result = await api.getAgenda();
    expect(result.source).toBe("live");
    expect(String(fetch.mock.calls[0]?.[0])).toBe("https://api.example.test/v1/plate");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(result.data).toMatchObject({
      days: null,
      events: null,
      details: null,
      slots: null,
      pins: null,
      rules: null,
      plate: { today: plate.today, asOf: plate.as_of, rows: plate.rows },
    });
  });
  it("FR_PB an empty plate stays an empty live list with unavailable calendar data", async () => {
    const { api } = apiFor({ ...plate, rows: [] });
    expect(await api.getAgenda()).toMatchObject({
      source: "live",
      data: { events: null, plate: { rows: [], parked: [], truncated: false } },
    });
  });
  it.each([401, 403, 500, 503])("FR_UX_14 HTTP %i remains a typed failure", async (status) => {
    const { api } = apiFor({ detail: "unavailable" }, status);
    await expect(api.getAgenda()).rejects.toMatchObject({ name: "TiloApiError", status });
  });
  it.each([null, {}, { ...plate, rows: [{}] }, { ...plate, parked: null }])(
    "FR_PB unreadable plate is not sample data: %j",
    async (body) => {
      await expect(apiFor(body).api.getAgenda()).rejects.toBeInstanceOf(TiloApiError);
    },
  );
  it("FR_UX_14 absent API origin stays NotBuilt without fetching", async () => {
    await expect(createLiveApi().getAgenda()).rejects.toBeInstanceOf(NotBuilt);
  });
  it("FR_UX_14 a network failure stays a typed retryable error", async () => {
    const api = createLiveApi({
      baseUrl: "https://api.example.test",
      fetch: async () => {
        throw new TypeError("offline");
      },
    });
    await expect(api.getAgenda()).rejects.toMatchObject({
      name: "TiloApiError",
      status: null,
      retryable: true,
    });
  });
});
