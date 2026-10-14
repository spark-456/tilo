import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";

it("W-DEAD-1 keeps the superseded title hook and unwired Park placeholder retired", () => {
  // Park uses app/pageTitle.tsx and the explicit lazy page registry after cutover.
  for (const file of ["documentTitle.ts", "park/app/Placeholder.tsx"]) {
    expect(existsSync(resolve(__dirname, file)), file).toBe(false);
  }
});
