// Runs in a child process (spawned by typecheck.ts): type-checks every file under src/park and test-support/park
// with the web app's own tsconfig and prints the errors as a JSON array of strings on stdout. Plain ESM so the
// child needs no TypeScript loader. A separate process keeps the ~10-80 s synchronous ts.createProgram off the
// vitest worker's event loop (a blocked worker misses vitest's 60 s RPC timeout and the run dies).
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const WEB_DIR = path.resolve(process.argv[2]);
const PARK_DIR = path.join(WEB_DIR, "src", "park");

function walk(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return walk(p);
    return /\.(ts|tsx)$/.test(e.name) ? [p] : [];
  });
}

const read = ts.readConfigFile(path.join(WEB_DIR, "tsconfig.json"), ts.sys.readFile);
const parsed = ts.parseJsonConfigFileContent(read.config, ts.sys, WEB_DIR);
const roots = [...walk(PARK_DIR), ...walk(path.join(WEB_DIR, "test-support", "park"))];
const program = ts.createProgram({ rootNames: roots, options: parsed.options });
const parkFiles = new Set(roots.map((r) => path.resolve(r)));
const errors = ts
  .getPreEmitDiagnostics(program)
  .filter((d) => d.file && parkFiles.has(path.resolve(d.file.fileName)))
  .map((d) => {
    const { line } = d.file?.getLineAndCharacterOfPosition(d.start ?? 0) ?? { line: 0 };
    const rel = path.relative(WEB_DIR, d.file?.fileName ?? "").replaceAll("\\", "/");
    return `${rel}:${line + 1} TS${d.code} ${ts.flattenDiagnosticMessageText(d.messageText, " ")}`;
  });
process.stdout.write(JSON.stringify(errors));
