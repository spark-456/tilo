import { expect, it } from "vitest";
import { API_DETAIL_MESSAGES } from "./errorCodes";
import { HttpClient, TiloApiError, displayApiError } from "./http";

it.each(Object.entries(API_DETAIL_MESSAGES))("X-APIERR-1 maps fixed code %s", (code, sentence) => {
  expect(sentence).toMatch(/^[A-Z].+[.!?]$/);
  expect(displayApiError(new TiloApiError(code, 409, false))).toBe(sentence);
});

it.each(["bad_cursor", "not_found", "already_rated", "inconsistent_ledger"])(
  "X-APIERR-1 reads the fixed detail %s through HTTP",
  async (detail) => {
    const client = new HttpClient({
      baseUrl: "https://api.test",
      fetch: async () => new Response(JSON.stringify({ detail }), { status: 409 }),
    });
    const error = await client.getJson("/worlds").catch((error: unknown) => error);
    expect(displayApiError(error)).toBe(API_DETAIL_MESSAGES[detail]);
  },
);
it.each(["cards_unavailable", "bot_unavailable", "unknown"])(
  "X-APIERR-1 reads the unavailable detail %s through HTTP",
  async (detail) => {
    const client = new HttpClient({
      baseUrl: "https://api.test",
      fetch: async () => new Response(JSON.stringify({ detail }), { status: 503 }),
    });
    const error = await client.getJson("/cards").catch((error: unknown) => error);
    expect(displayApiError(error)).toBe(API_DETAIL_MESSAGES[detail]);
  },
);
it("X-APIERR-1 retains the uncertain write warning over a specific refusal", () => {
  expect(displayApiError(new TiloApiError("write_failed", 503, true, true))).toBe(
    "We could not confirm it. Reload before trying again.",
  );
});
