// WEB-2 typecheck over src/park/components, src/park/dev, and test-support/park/components.
// Lives in *.typecheck.test.ts so Vitest runs it inside the single-fork `typecheck` project
// and shares one tsc child process with the rest of the Park typecheck suite (#575).
import { describe, expect, it } from "vitest";
import { parkTypeErrors } from "../../../test-support/park/typecheck";

describe("WEB_2_typecheck: the new files compile with the repo's strict options", () => {
  it(
    "WEB_2_typecheck_components_dev_and_their_tests_have_no_type_errors",
    { timeout: 240_000 },
    async () => {
      const mine = (await parkTypeErrors()).filter((e) =>
        /^(?:src\/park\/components\/|src\/park\/dev\/|test-support\/park\/components)/.test(e),
      );
      expect(mine).toEqual([]);
    },
  );
});
