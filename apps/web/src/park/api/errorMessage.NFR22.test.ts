import { expect, it } from "vitest";
import { HttpClient, TiloApiError, displayApiError } from "../../api/http";

it.each([
  ["allowance_capped", "Your allowance is used up. Try again when it resets."],
  ["rate_limited", "Too many requests. Wait a moment and try again."],
  ["version_conflict", "This changed while you were working. Reload and try again."],
])("NFR22 maps the API detail %s into plain words", (detail, words) => {
  expect(displayApiError(new TiloApiError(detail, 409, false))).toBe(words);
});
it("NFR22 preserves approved 503 detail mapping without leaking unknown server text", async () => {
  for (const [detail, expected] of [
    ["not_configured", "This feature is not configured on this server."],
    [
      "The safety screen is unavailable; nothing was stored.",
      "The safety screen is unavailable. Try again later.",
    ],
    ["private credentials and stack trace", "Tilo had a problem on its side."],
  ]) {
    const client = new HttpClient({
      baseUrl: "https://api.test",
      fetch: async () => new Response(JSON.stringify({ detail }), { status: 503 }),
    });
    const error = await client.getJson("/costs").catch((e: unknown) => e);
    expect(displayApiError(error)).toBe(expected);
  }
});
it("NFR22 never exposes unknown exceptions or unapproved API text", () => {
  for (const error of [
    new Error("private account token"),
    new TiloApiError("<script>private</script>", 500, true),
    new TiloApiError("private account token", 403, false),
  ]) {
    expect(displayApiError(error)).not.toMatch(/private|token|script/);
  }
});
