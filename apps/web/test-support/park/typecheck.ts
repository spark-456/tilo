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
const DEFAULT_TIMEOUT_MS = 175_000;

let cached: Promise<string[]> | undefined;

export interface TypecheckWorkerOptions {
  args?: string[];
  timeoutMs?: number;
}

export interface TypecheckWorkerHandle {
  pid: number | undefined;
  promise: Promise<string[]>;
}

export function runTypecheckWorker(options: TypecheckWorkerOptions = {}): TypecheckWorkerHandle {
  const args = options.args ?? [WORKER, WEB_DIR];
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  let pid: number | undefined;

  const promise = new Promise<string[]>((resolve, reject) => {
    const child = spawn(process.execPath, args, {
      cwd: WEB_DIR,
      stdio: ["ignore", "pipe", "pipe"],
    });
    pid = child.pid;
    let out = "";
    let err = "";
    let timedOut = false;

    const killChild = (): void => {
      if (child.exitCode === null && !child.killed) {
        child.kill();
      }
    };
    const timer = setTimeout(() => {
      timedOut = true;
      killChild();
    }, timeoutMs);
    process.once("exit", killChild);

    const cleanup = (): void => {
      clearTimeout(timer);
      process.removeListener("exit", killChild);
    };

    child.stdout.on("data", (d: Buffer) => {
      out += d.toString();
    });
    child.stderr.on("data", (d: Buffer) => {
      err += d.toString();
    });
    child.on("error", (e) => {
      cleanup();
      reject(e);
    });
    child.on("close", (code) => {
      cleanup();
      if (timedOut) {
        return reject(new Error(`typecheck worker timed out after ${timeoutMs} ms`));
      }
      if (code !== 0)
        return reject(new Error(`typecheck worker exited ${code}: ${err.slice(0, 2000)}`));
      try {
        resolve(JSON.parse(out) as string[]);
      } catch (e) {
        reject(new Error(`typecheck worker printed no JSON: ${String(e)} ${out.slice(0, 500)}`));
      }
    });
  });

  return { pid, promise };
}

export function parkTypeErrors(): Promise<string[]> {
  cached ??= runTypecheckWorker().promise;
  return cached;
}

/** Compile an in-memory kit consumer in its own bounded child, leaving Vitest responsive. */
export function kitProbeErrors(source: string): Promise<string[]> {
  return runTypecheckWorker({
    args: [WORKER, WEB_DIR, "kit-probe", Buffer.from(source).toString("base64")],
  }).promise;
}
