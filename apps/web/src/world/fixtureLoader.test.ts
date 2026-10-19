import { readFileSync } from "node:fs";
import { afterEach, expect, it, vi } from "vitest";
import { loadFixture } from "./fixtureLoader";

afterEach(() => vi.unstubAllGlobals());

it("QA_2 Hosting serves recorded jsonl streams as application/x-ndjson", () => {
  const config = JSON.parse(
    readFileSync(new URL("../../../../firebase.json", import.meta.url), "utf8"),
  );
  expect(config.hosting.headers).toContainEqual({
    source: "**/*.jsonl",
    headers: [{ key: "Content-Type", value: "application/x-ndjson" }],
  });
});

it("QA_2 loads an ndjson recorded stream", async () => {
  const event = { type: "world.started", seq: 1 };
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(Response.json({ id: "recorded" }))
      .mockResolvedValueOnce(
        new Response(`${JSON.stringify(event)}\n`, {
          headers: { "Content-Type": "application/x-ndjson" },
        }),
      ),
  );
  expect(await loadFixture("village-basic")).toEqual({
    layout: { id: "recorded" },
    events: [event],
  });
});

it("QA_2 keeps rejecting an HTML fallback even with status 200", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(Response.json({}))
      .mockResolvedValueOnce(
        new Response("<html>fallback</html>", { headers: { "Content-Type": "text/html" } }),
      ),
  );
  await expect(loadFixture("missing")).rejects.toThrow("failed to load");
});
