import { expect, it } from "vitest";
import { differentBuild, liveBuildSha } from "./staleBuild";

it("STALE_BUILD_reloads_only_for_a_different_live_build", () => {
  expect(differentBuild("b9e4a4368c4f08254272d35174624ae92f9ea651", "b9e4a436")).toBe(false);
  expect(differentBuild("386d598ede830bd297024e46569b541e41eade58", "b9e4a436")).toBe(true);
  expect(differentBuild(null, "b9e4a436")).toBe(false);
  expect(differentBuild("386d598e", "dev")).toBe(false);
});

it("STALE_BUILD_reads_the_live_sha_from_the_page_meta", async () => {
  const page = '<head><meta name="tilo-build" content="386d598ede830bd2"></head>';
  const ok = (async () => new Response(page)) as unknown as typeof fetch;
  expect(await liveBuildSha(ok)).toBe("386d598ede830bd2");
  const down = (async () => {
    throw new Error("offline");
  }) as unknown as typeof fetch;
  expect(await liveBuildSha(down)).toBeNull();
});
