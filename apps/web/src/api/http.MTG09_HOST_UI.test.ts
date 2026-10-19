// MTG09_HOST_UI (FR-MTG-09, ticket MEETINGS-1): the HttpClient call under the S-26 "Host this meeting"
// button. `POST /v1/meetings/{id}/host` with body `{}` (services/api/tests/API_MTG09_b.md): 200
// `{world_id}` (the gate card is posted to the world's card list, it is not in the reply), 404 / 409 /
// 422 (with the connector's `rule`) / 403 / 503 refusals. The call is not on the TiloClient interface.
// Fetch is mocked; no network.
import { describe, expect, it, vi } from "vitest";
import { HttpClient, TiloApiError } from "./http";

const BASE = "https://api.test";

function script(...replies: Array<Response | Error>) {
  const calls: Array<{ url: string; init: RequestInit | undefined }> = [];
  const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    const next = replies.shift();
    if (!next) throw new Error("unscripted call");
    if (next instanceof Error) throw next;
    return next;
  });
  return { calls, fetch: fetchMock as unknown as typeof fetch };
}
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const failure = async (reply: Response | Error): Promise<TiloApiError> => {
  const { fetch } = script(reply);
  const error = await new HttpClient({ baseUrl: BASE, fetch }).hostMeeting("mt_q4_plan_next").then(
    () => null,
    (e: unknown) => e,
  );
  expect(error).toBeInstanceOf(TiloApiError);
  return error as TiloApiError;
};

describe("MTG09_HOST_UI HttpClient.hostMeeting", () => {
  it("MTG09_HOST_UI posts once to /v1/meetings/{id}/host with the body {} and returns the world id", async () => {
    const { calls, fetch } = script(json({ world_id: "w_meet_1" }));
    const result = await new HttpClient({ baseUrl: BASE, fetch }).hostMeeting("mt_q4_plan_next");
    expect(result).toEqual({ world_id: "w_meet_1" });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe(`${BASE}/v1/meetings/mt_q4_plan_next/host`);
    expect(calls[0]?.init?.method).toBe("POST");
    expect(calls[0]?.init?.body).toBe("{}");
  });

  it("MTG09_HOST_UI a reply with no world id is an unreadable reply, never a started run", async () => {
    for (const body of [{}, { world_id: 7 }, { world_id: "" }, null, []]) {
      const error = await failure(json(body));
      expect(error.retryable).toBe(true);
      expect(error.write).toBe(true);
    }
  });

  it("MTG09_HOST_UI a 404 keeps its status and its refusal word", async () => {
    const error = await failure(json({ detail: "not_found" }, 404));
    expect([error.status, error.refusal, error.retryable, error.write]).toEqual([
      404,
      "not_found",
      false,
      true,
    ]);
  });

  it("MTG09_HOST_UI a 409 keeps which reason it was", async () => {
    expect((await failure(json({ detail: "not_hostable" }, 409))).refusal).toBe("not_hostable");
    expect((await failure(json({ detail: "already_hosted" }, 409))).refusal).toBe("already_hosted");
  });

  it("MTG09_HOST_UI a 422 keeps the connector's rule and never its text", async () => {
    const error = await failure(
      json({ detail: "the window is not in the future", rule: "MH-02" }, 422),
    );
    expect([error.status, error.refusal]).toEqual([422, "MH-02"]);
  });

  it("MTG09_HOST_UI a 503 not_configured is a 503 with its refusal word", async () => {
    const error = await failure(json({ detail: "not_configured" }, 503));
    expect([error.status, error.refusal]).toEqual([503, "not_configured"]);
  });

  it("MTG09_HOST_UI a 403 and a dropped connection are typed failures of a write", async () => {
    expect((await failure(json({ detail: "forbidden" }, 403))).status).toBe(403);
    const dropped = await failure(new TypeError("Failed to fetch"));
    expect([dropped.status, dropped.retryable, dropped.write]).toEqual([null, true, true]);
  });

  it("MTG09_HOST_UI a refusal word that is not a short token is dropped", async () => {
    expect((await failure(json({ detail: "Not <b>Found</b>" }, 404))).refusal).toBeNull();
    expect((await failure(json({ detail: "x".repeat(80) }, 409))).refusal).toBeNull();
    expect((await failure(json({ detail: "x", rule: "MH-0<script>" }, 422))).refusal).toBe("x");
  });

  it("MTG09_HOST_UI the id is path-encoded", async () => {
    const { calls, fetch } = script(json({ world_id: "w1" }));
    await new HttpClient({ baseUrl: BASE, fetch }).hostMeeting("mt_a/../b");
    expect(calls[0]?.url).toBe(`${BASE}/v1/meetings/mt_a%2F..%2Fb/host`);
  });
});
