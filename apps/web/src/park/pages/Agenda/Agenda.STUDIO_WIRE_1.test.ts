// STUDIO-WIRE-1 (FR-UX-14, FR-PB-01): the Agenda page's "Pinboards" list is already wired to GET /v1/pinboards, so the
// side card's pointer to it is true. This pins that read so the copy cannot drift from the data.
import { expect, it, vi } from "vitest";
import { peopleListsApi } from "../../api/live/peopleLists";

it("FR_UX_14_STUDIO_WIRE_1 the pinboards list reads GET /v1/pinboards items", async () => {
  const getJson = vi.fn(async () => ({ items: [], truncated: false }));
  const reply = await peopleListsApi({ getJson } as never).getPinboards();
  expect(getJson).toHaveBeenCalledWith("/v1/pinboards");
  expect(reply.source).toBe("live");
  expect(reply.data).toEqual({ rows: [], truncated: false });
});
