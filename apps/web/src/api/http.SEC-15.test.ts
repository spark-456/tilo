// SEC-15 (docs/prd-supplement-2026-10-05.md section 4): the web client turns the server's access refusal into
// something a page can render. The API answers a visitor with 403 {"detail", "code": "under_construction"} and a
// person who has not answered the sign-up question with 403 {"detail", "code": "declaration_required"}
// (services/api/tests/API_SEC_15.md). `TiloApiError.code` carries that stable code, or null when the server sent none.
import { describe, expect, it } from "vitest";
import { HttpClient, TiloApiError } from "./http";

const UNDER_CONSTRUCTION = "Tilo is still under construction and not open to the public.";

function clientAnswering(status: number, body: unknown): HttpClient {
  const fetchFn = (async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    })) as typeof fetch;
  return new HttpClient({ baseUrl: "http://api.test", fetch: fetchFn });
}

async function failureOf(client: HttpClient): Promise<TiloApiError> {
  try {
    await client.submitIntake("Prepare the weekly summary.", []);
  } catch (error) {
    expect(error).toBeInstanceOf(TiloApiError);
    return error as TiloApiError;
  }
  throw new Error("the call should have failed");
}

describe("SEC-15 the client carries the access refusal's code", () => {
  it("SEC-15 a visitor's 403 keeps its code and the server's own sentence, and is not retryable", async () => {
    const error = await failureOf(
      clientAnswering(403, { detail: UNDER_CONSTRUCTION, code: "under_construction" }),
    );
    expect(error.status).toBe(403);
    expect(error.code).toBe("under_construction");
    expect(error.message).toBe(UNDER_CONSTRUCTION);
    expect(error.retryable).toBe(false);
  });

  it("SEC-15 a missing declaration's 403 carries declaration_required", async () => {
    const error = await failureOf(
      clientAnswering(403, {
        detail: "Tell Tilo whether you are a visitor or a judge.",
        code: "declaration_required",
      }),
    );
    expect(error.code).toBe("declaration_required");
  });

  it("SEC-15 a 403 with no code (a role refusal) has code null, not undefined", async () => {
    const error = await failureOf(clientAnswering(403, { detail: "Forbidden" }));
    expect(error.status).toBe(403);
    expect(error.code).toBeNull();
  });

  it("SEC-15 only a short lower-case code is kept; markup or a long value in `code` is dropped", async () => {
    for (const code of ["<script>x</script>", "A".repeat(80), 7, { a: 1 }, "Under Construction"]) {
      const error = await failureOf(clientAnswering(403, { detail: "No.", code }));
      expect(error.code).toBeNull();
    }
  });

  it("SEC-15 a server error never reports an access code", async () => {
    const error = await failureOf(
      clientAnswering(500, { detail: "boom", code: "under_construction" }),
    );
    expect(error.code).toBeNull();
    expect(error.retryable).toBe(true);
  });
});
