// SEC-10 (SEC-SWEEP-1, #570 follow-up): the web's default fetch never follows a redirect, so a response that redirects
// can never carry the sign-in token or the App Check token to another address.
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpClient } from "./http";

afterEach(() => vi.restoreAllMocks());

describe("SEC-10 the default fetch refuses redirects", () => {
  it("SEC-10 every call the client makes carries redirect: error", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(
        async () =>
          new Response("{}", { status: 200, headers: { "content-type": "application/json" } }),
      );
    const http = new HttpClient({
      baseUrl: "https://api.example.test",
      authToken: async () => "tok",
    });
    await http.getJson("/costs");
    await http.postJson("/x", {});
    expect(spy).toHaveBeenCalledTimes(2);
    for (const [, init] of spy.mock.calls) expect((init as RequestInit).redirect).toBe("error");
  });

  it("SEC-10 a fetch a caller injects is its own (tests, the stage)", async () => {
    const own = vi.fn(
      async () =>
        new Response("{}", { status: 200, headers: { "content-type": "application/json" } }),
    );
    await new HttpClient({
      baseUrl: "https://api.example.test",
      fetch: own as unknown as typeof fetch,
    }).getJson("/costs");
    expect(own).toHaveBeenCalledTimes(1);
  });
});
