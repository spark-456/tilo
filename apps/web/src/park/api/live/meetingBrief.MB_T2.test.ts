import { expect, it, vi } from "vitest";
import { TiloApiError } from "../../../api/http";
import { meetingBriefApi } from "./meetingBrief";

const meeting = { id: "mt_a", brief_requested: true, auto_report: false };
const doc = {
  v: "1.0",
  meeting_id: "mt_a",
  flagged: false,
  agenda_points: [{ title: "Launch", minutes: null, talk_points: [] }],
  carry_over: [],
};
const http = () => ({
  getJson: vi.fn(async (path: string) => (path.endsWith("/brief") ? doc : meeting)),
  postJson: vi.fn(async () => doc),
  sendJson: vi.fn(async () => meeting),
});

it("MB_T2 client reads only the owner meeting and its stored brief", async () => {
  const client = http();
  const api = meetingBriefApi(client);
  expect(await api.meeting("mt_a")).toEqual({ briefRequested: true, autoReport: false });
  expect((await api.read("mt_a"))?.agenda_points[0]?.title).toBe("Launch");
  expect(client.postJson).not.toHaveBeenCalled();
  await expect(api.meeting("wrong_id")).rejects.toThrow();
});

it("MB_T2 client distinguishes not_ready from a missing route and PATCHes only one switch", async () => {
  const client = http();
  client.getJson.mockRejectedValueOnce(
    new TiloApiError("not_ready", 404, false, false, "not_ready"),
  );
  const api = meetingBriefApi(client);
  expect(await api.read("mt_a")).toBeNull();
  client.getJson.mockRejectedValueOnce(new TiloApiError("not_found", 404, false));
  await expect(api.read("mt_a")).rejects.toThrow();
  expect(await api.switch("mt_a", "auto_report", true)).toEqual({ autoReport: true });
  expect(client.sendJson).toHaveBeenCalledWith("PATCH", "/v1/meetings/mt_a", { auto_report: true });
});
