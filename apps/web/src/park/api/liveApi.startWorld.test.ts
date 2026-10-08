// FR-UX-13 acceptance: the live Api's `startWorld` is the REAL intake call, the same one the legacy S-01 makes
// (`HttpClient.submitIntake`: POST {base}/intake, multipart form with the task `text` and its `files`).
// Today every method but three is NotBuilt. Here the Api is built over a fake fetch, so no network is used.
// Facts the tests rely on (src/api/http.ts): the intake takes only `text` and `files`; it has no size of job,
// routine or workspace field, so the three composer sizes send the same payload shape and the size only shapes
// the world the page shows (BQ rows at the end of docs/open-questions.md). A write is one POST per call, never retried.
import { describe, expect, it, vi } from "vitest";
import { BRIEF_SUPPLIER_COMPARISON } from "../../api/fixtures/brief";
import { TiloApiError } from "../../api/http";
import { TIERS } from "./fixtures/tiers";
import { createLiveApi } from "./liveApi";
import type { TierKey } from "./types";

const BASE = "https://api.example.test";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const INTAKE = {
  task_id: "t_abc123",
  brief: BRIEF_SUPPLIER_COMPARISON,
  questions: [],
  files: [],
};

type Reply = () => Response | Promise<Response>;
function setup(reply: Reply) {
  const fetchSpy = vi.fn(async (_url: string | URL | Request, _init?: RequestInit) => reply());
  const api = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
  return { api, fetchSpy };
}
const MODES: TierKey[] = ["quick", "routine", "workspace"];

describe("FR_UX_13 live Api: startWorld is the real intake call", () => {
  it.each(MODES)(
    "FR_UX_13 live Api: startWorld(%s) makes one multipart POST /intake with the text and no other field, and answers from the server's reply",
    async (mode) => {
      const { api, fetchSpy } = setup(() => json(INTAKE));
      const got = await api.startWorld(mode, "Compare three suppliers");

      expect(fetchSpy, "one request, no reads around it").toHaveBeenCalledTimes(1);
      const [url, init] = fetchSpy.mock.calls[0] ?? [];
      expect(String(url)).toBe(`${BASE}/intake`);
      expect(init?.method).toBe("POST");
      const form = init?.body;
      expect(form instanceof FormData, "multipart form, as the legacy S-01 sends it").toBe(true);
      const keys = [...(form as FormData).keys()];
      expect(keys, "text only: the intake has no size, routine or workspace field").toEqual([
        "text",
      ]);
      expect((form as FormData).get("text")).toBe("Compare three suppliers");

      expect(got.source).toBe("live");
      expect(got.data.ok).toBe(true);
      expect(got.data.world.id, "the world is the server's task").toBe("t_abc123");
      expect(got.data.world.isNew).toBe(true);
      expect(got.data.world.tier, "the size the person chose").toBe(TIERS[mode].tier);
    },
  );

  it.each([
    [
      "not signed in (401)",
      () => json({ detail: "Unauthorized" }, 401),
      { status: 401, message: "You need to sign in to do this.", retryable: false },
    ],
    [
      "a 5xx",
      () => json({ detail: "boom" }, 503),
      { status: 503, message: "Tilo had a problem on its side.", retryable: true },
    ],
    [
      "an intake limit",
      () => json({ error: "The task text is over the 4,000 character limit." }, 422),
      {
        status: 422,
        message: "The task text is over the 4,000 character limit.",
        retryable: false,
      },
    ],
    [
      "a network failure",
      () => {
        throw new TypeError("connect ECONNREFUSED 10.0.0.7:8080");
      },
      {
        status: null,
        message: "Tilo could not be reached. Check your connection and try again.",
        retryable: true,
      },
    ],
  ])(
    "FR_UX_13 live Api: startWorld rejects with the shared TiloApiError on %s, makes one POST and returns no world",
    async (_name, reply, want) => {
      const { api, fetchSpy } = setup(reply);
      const err = await api.startWorld("quick", "Compare three suppliers").then(
        () => null,
        (e: unknown) => e,
      );
      expect(err).toBeInstanceOf(TiloApiError);
      expect(err).toMatchObject({ ...want, write: true });
      expect((err as Error).message).not.toContain("10.0.0.7");
      expect(fetchSpy, "a write is never retried by itself").toHaveBeenCalledTimes(1);
    },
  );

  it("FR_UX_13 live Api: a 200 that is not an intake result is an unreadable reply, never a world", async () => {
    const { api } = setup(() => json({ nope: true }));
    const err = await api.startWorld("quick", "Compare three suppliers").then(
      () => null,
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(TiloApiError);
    expect((err as Error).message).not.toMatch(/undefined|Cannot read|TypeError/);
  });
});
