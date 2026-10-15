import { expect, it } from "vitest";
import { HttpClient, TiloApiError, displayApiError } from "./http";

const mappings = [
  ["not_configured", 503, "This feature is not configured on this server."],
  ["unavailable", 503, "This feature is unavailable right now. Try again in a moment."],
  ["body_too_large", 413, "This is too large to send. Reduce its size and try again."],
  ["allowance_capped", 429, "Your allowance is used up. Try again when it resets."],
  ["rate_limited", 429, "Too many requests. Wait a moment and try again."],
  ["not_understood", 422, "Try rewriting the description to say what you want Tilo to do."],
  ["store_unavailable", 503, "Stored information is unavailable. Try again in a moment."],
  ["spend_cap_reached", 403, "Your spending limit has been reached."],
] as const;

it.each(mappings)(
  "M2-CODES-1 maps %s from real code and detail responses",
  async (code, status, words) => {
    for (const body of [{ code, detail: "private server text" }, { detail: code }]) {
      const client = new HttpClient({
        baseUrl: "https://api.test",
        fetch: async () => new Response(JSON.stringify(body), { status }),
      });
      const error = await client.getJson("/costs").catch((failure: unknown) => failure);
      expect(error).toBeInstanceOf(TiloApiError);
      expect(displayApiError(error)).toBe(words);
    }
  },
);

it.each(["__proto__", "constructor", "toString", "private_token_123", "<script>secret</script>"])(
  "M2-CODES-1 never displays unknown code %s or arbitrary server text",
  (code) => {
    expect(displayApiError(new TiloApiError("private server text", 503, true, false, code))).toBe(
      "Tilo had a problem on its side.",
    );
  },
);

it("M2-CODES-1 preserves replay-only guidance before a generic unavailable code", () => {
  expect(displayApiError(new TiloApiError("private", 503, false, true, "unavailable", true))).toBe(
    "Live models are unavailable right now, so nothing new was started. Finished runs can still be replayed.",
  );
});

it("M2-CODES-1 explains uncertain writes without implying nothing changed", () => {
  for (const status of [null, 503]) {
    expect(displayApiError(new TiloApiError("private", status, true, true, "unavailable"))).toBe(
      "We could not confirm it. Reload before trying again.",
    );
  }
});
