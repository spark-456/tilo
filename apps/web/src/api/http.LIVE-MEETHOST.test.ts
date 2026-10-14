import { describe, expect, it, vi } from "vitest";
import { createConnectFlow } from "./connect";
import { HttpClient, TiloApiError } from "./http";

const body = {
  connectors: [
    {
      id: "meeting_host",
      name: "Meeting host",
      state: "available",
      state_known: false,
      scopes: [],
      expires_at: null,
      unavailable_reason: "not_configured",
    },
  ],
};

describe("LIVE-MEETHOST session reads", () => {
  it("coalesces Connectors and World reads and retains only explicit not-configured", async () => {
    const wire = { connectors: body.connectors.map(({ unavailable_reason, ...row }) => row) };
    const fetch = vi.fn(
      async () =>
        new Response(JSON.stringify(wire), {
          headers: { "X-Tilo-Meeting-Host": "not_configured" },
        }),
    );
    const first = new HttpClient({ baseUrl: "https://api.test", fetch });
    const second = new HttpClient({ baseUrl: "https://api.test", fetch });
    const flow = createConnectFlow(second);
    const [world, host] = await Promise.all([first.getJson("/v1/connectors"), flow.meetingHost()]);
    expect(world).toEqual(body);
    expect(host).toBe("not_configured");
    expect(await flow.meetingHost()).toBe("not_configured");
    expect(await first.getJson("/v1/connectors")).toEqual(body);
    expect(fetch).toHaveBeenCalledTimes(1);
    await new HttpClient({ baseUrl: "https://other.test", fetch }).getJson("/v1/connectors");
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it.each([401, 403, 503, 500])("does not retain unrelated HTTP %s failures", async (status) => {
    const fetch = vi.fn(async () => new Response('{"detail":"unknown"}', { status }));
    const client = new HttpClient({ baseUrl: "https://api.test", fetch });
    for (let n = 0; n < 2; n++)
      await expect(client.getJson("/v1/connectors")).rejects.toBeInstanceOf(TiloApiError);
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("unknown views and successful connections are read afresh", async () => {
    for (const row of [
      { ...body.connectors[0], unavailable_reason: undefined },
      { ...body.connectors[0], state_known: true, state: "connected" },
    ]) {
      const fetch = vi.fn(async () => new Response(JSON.stringify({ connectors: [row] })));
      const flow = createConnectFlow(new HttpClient({ baseUrl: "https://api.test", fetch }));
      await flow.meetingHost();
      await flow.meetingHost();
      expect(fetch).toHaveBeenCalledTimes(2);
    }
  });
});
