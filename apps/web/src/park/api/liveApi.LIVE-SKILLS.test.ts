import { expect, it, vi } from "vitest";
import { createLiveApi } from "./liveApi";

it("LIVE-SKILLS requests and lists shipped builtins without invented run history or edit access", async () => {
  const fetch = vi.fn(
    async (_url: unknown) =>
      new Response(
        JSON.stringify({
          skills: [],
          builtins: [
            { id: "web-research", description: "Research public sources.", version: "1.0.0" },
          ],
        }),
        { headers: { "content-type": "application/json" } },
      ),
  );
  const api = createLiveApi({ baseUrl: "https://api.example.test", fetch });
  const result = await api.getSkills();
  expect(String(fetch.mock.calls[0]?.[0])).toBe(
    "https://api.example.test/v1/skills?include_builtin=true",
  );
  expect(result.source).toBe("live");
  expect(result.data).toMatchObject([
    {
      id: "web-research",
      name: "Web Research",
      owner: "Tilo",
      builtin: true,
      description: "Research public sources.",
      steps: [],
      runs: null,
      rate: null,
    },
  ]);
  expect(result.data[0]?.fix).toBeUndefined();
});
