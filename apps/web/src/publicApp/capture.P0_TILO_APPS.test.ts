import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { CAPTURE_SCRIPT, captureHtml } from "./capture";

it("P0-TILO-APPS keeps the capture script hash pinned in Hosting CSP", () => {
  const hash = createHash("sha256").update(CAPTURE_SCRIPT).digest("base64");
  const hosting = JSON.parse(readFileSync("../../firebase.json", "utf8")) as {
    hosting: { headers: Array<{ source: string; headers: Array<{ value: string }> }> };
  };
  for (const source of ["**", "/u/**"]) {
    const policy = hosting.hosting.headers.find((entry) => entry.source === source)?.headers[0]
      ?.value;
    expect(policy).toContain(`'sha256-${hash}'`);
  }
  expect(captureHtml("<form></form>")).toContain(`<script>${CAPTURE_SCRIPT}</script>`);
});
