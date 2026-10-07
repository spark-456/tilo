// SEC-10: a token the getter returns that cannot be a header value (a bad character, too long) must not turn the call
// into "Tilo could not be reached": the request goes out with no header instead. No network: a fake fetch.
import { describe, expect, it } from "vitest";
import { HttpClient } from "./http";

function client(token: string) {
  const seen: Headers[] = [];
  const http = new HttpClient({
    baseUrl: "http://api.test",
    fetch: (async (_url: RequestInfo | URL, init?: RequestInit) => {
      seen.push(new Headers(init?.headers));
      return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
    }) as typeof fetch,
    appCheckToken: async () => token,
  });
  return { http, seen };
}

describe("SEC-10 a token that cannot be a header value sends no header", () => {
  it("SEC-10 line breaks, spaces, non-ASCII, control characters and over-long tokens are not sent", async () => {
    for (const bad of [
      "abc\r\nX-Evil: 1",
      "has space",
      "café.token.x",
      "tab\there",
      "nul\u0000byte",
      `${"a".repeat(4097)}`,
    ]) {
      const { http, seen } = client(bad);
      await expect(http.getJson("/worlds")).resolves.toEqual({});
      expect(seen).toHaveLength(1);
      expect(seen[0]?.has("x-firebase-appcheck"), JSON.stringify(bad)).toBe(false);
    }
  });

  it("SEC-10 a JWT-shaped token (base64url and dots) is sent as it is", async () => {
    const jwt = ["eyJhbGciOiJSUzI1NiJ9", "eyJzdWIiOiJ4In0", "c2ln-_0=+/~"].join(".");
    const { http, seen } = client(jwt);
    await http.getJson("/worlds");
    expect(seen[0]?.get("x-firebase-appcheck")).toBe(jwt);
  });
});
