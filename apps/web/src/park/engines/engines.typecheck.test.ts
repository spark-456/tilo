// WEB-1b: the engine ports are typed code, not a JS file renamed. Vitest does not evaluate types, so this
// runs the TypeScript compiler (apps/web/tsconfig.json options: strict, noUncheckedIndexedAccess,
// exactOptionalPropertyTypes) over src/park/engines and fails on any error, on a ts directive, and on any
// use of `any` outside the one children type of the `H` factory. The builder also runs
// `pnpm --filter @tilo/web run typecheck`.
import { describe, expect, it } from "vitest";
import {
  anyUses,
  engineSources,
  engineTypeErrors,
  tsDirectives,
} from "../../../test-support/park/engineTypecheck";

describe("WEB_1b_typecheck: the engines compile with the repo's strict options", () => {
  it("WEB_1b_typecheck_the_engine_files_exist", () => {
    const names = engineSources().map((f) => f.replaceAll("\\", "/").split("/").pop());
    expect(names).toEqual(expect.arrayContaining(["types.ts", "world.ts", "park.ts"]));
  });

  it("WEB_1b_typecheck_engines_have_no_type_errors", { timeout: 240_000 }, async () => {
    expect(
      engineSources().length,
      "nothing to compile: the engine files are missing",
    ).toBeGreaterThanOrEqual(3);
    expect(await engineTypeErrors()).toEqual([]);
  });

  it("WEB_1b_typecheck_no_ts_ignore_ts_nocheck_or_ts_expect_error", () => {
    expect(engineSources().length).toBeGreaterThanOrEqual(3);
    expect(tsDirectives()).toEqual([]);
  });

  it("WEB_1b_typecheck_no_any_except_at_most_one_in_types_ts", () => {
    expect(engineSources().length).toBeGreaterThanOrEqual(3);
    const uses = anyUses();
    expect(
      uses.filter((u) => !u.file.endsWith("park/engines/types.ts")),
      "`any` is only allowed in the children type of H (types.ts); use unknown or a real type elsewhere",
    ).toEqual([]);
    expect(uses.length, "at most one `any`, in types.ts").toBeLessThanOrEqual(1);
  });
});
