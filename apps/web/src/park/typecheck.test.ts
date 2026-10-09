// WEB-1a: Vitest does not evaluate types at runtime, so the expectTypeOf checks in park/api/types.test.ts
// would pass silently. This runs the TypeScript compiler (apps/web/tsconfig.json options: strict,
// noUncheckedIndexedAccess, exactOptionalPropertyTypes) over every file under src/park and
// test-support/park, and fails on any error. The builder also runs `pnpm --filter @tilo/web run typecheck`.
import { describe, expect, it } from "vitest";
import { parkTypeErrors, runTypecheckWorker } from "../../test-support/park/typecheck";

describe("WEB_1a_typecheck: park files compile with the repo's strict options", () => {
  it("WEB_1a_typecheck_park_has_no_type_errors", { timeout: 240_000 }, async () => {
    expect(await parkTypeErrors()).toEqual([]);
  });

  it("WEB_1a_typecheck_timeout_kills_the_child_process_by_its_own_pid", async () => {
    const exitListenersBefore = process.listenerCount("exit");
    const handle = runTypecheckWorker({
      args: ["-e", "setInterval(() => {}, 1000)"],
      timeoutMs: 100,
    });
    expect(typeof handle.pid).toBe("number");
    const pid = handle.pid as number;
    expect(pid).toBeGreaterThan(0);

    await expect(handle.promise).rejects.toThrow(/timed out/i);
    expect(() => process.kill(pid, 0)).toThrow();
    expect(process.listenerCount("exit")).toBe(exitListenersBefore);
  });
});
