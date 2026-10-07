// WEB-1a test support: type-checks every file under src/park (sources and tests) with the web app's
// own tsconfig, through the TypeScript API, so the expectTypeOf checks in the park tests are really
// enforced (Vitest does not evaluate types at runtime). Scoped to park files, so it stays fast.
//
// The compiler runs in a child process (typecheckWorker.mjs) and the result is awaited: ts.createProgram is
// synchronous and takes ~10 s alone and up to ~80 s on a loaded machine, and a vitest worker that blocks that
// long misses vitest's 60 s worker RPC ("Timeout calling onTaskUpdate", exit 1 with every test green). The
// answer is built once per process, so the files that ask share one child (vitest.config.ts runs the
// typecheck tests together in one fork).
import { spawn } from "node:child_process";
import path from "node:path";
import { PARK_DIR } from "./prototype";

const WEB_DIR = path.resolve(PARK_DIR, "..", "..");
const WORKER = path.join(WEB_DIR, "test-support", "park", "typecheckWorker.mjs");

let cached: Promise<string[]> | undefined;

function build(): Promise<string[]> {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [WORKER, WEB_DIR], {
      cwd: WEB_DIR,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (d: Buffer) => {
      out += d.toString();
    });
    child.stderr.on("data", (d: Buffer) => {
      err += d.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0)
        return reject(new Error(`typecheck worker exited ${code}: ${err.slice(0, 2000)}`));
      try {
        resolve(JSON.parse(out) as string[]);
      } catch (e) {
        reject(new Error(`typecheck worker printed no JSON: ${String(e)} ${out.slice(0, 500)}`));
      }
    });
  });
}

export function parkTypeErrors(): Promise<string[]> {
  cached ??= build();
  return cached;
}
