import { expect, it, vi } from "vitest";
import { HttpClient } from "./http";

it.each(["POST", "PUT", "DELETE"])(
  "TEAM_WEB_sample_refuses_%s_with_a_body_before_serialization_or_tokens",
  async (method) => {
    const fetch = vi.fn<typeof globalThis.fetch>();
    const token = vi.fn(async () => "unused");
    const serialize = vi.fn(() => {
      throw new Error("Must not serialize a refused sample write");
    });
    const http = new HttpClient({
      baseUrl: "https://api.test",
      fetch,
      authToken: token,
      appCheckToken: token,
    });
    for (const path of ["/worlds/w_sample_village_basic", "/worlds/w_sample_village_basic/share"])
      await expect(http.sendJson(method, path, { toJSON: serialize })).rejects.toMatchObject({
        code: "sample_is_a_replay",
      });
    expect(fetch).not.toHaveBeenCalled();
    expect(token).not.toHaveBeenCalled();
    expect(serialize).not.toHaveBeenCalled();
  },
);
