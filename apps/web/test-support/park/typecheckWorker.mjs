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
let roots = [...walk(PARK_DIR), ...walk(path.join(WEB_DIR, "test-support", "park"))];
const host = ts.createCompilerHost(parsed.options);
if (process.argv[3] === "kit-probe") {
  const probe = path.join(PARK_DIR, "engines", "__kit_probe__.ts");
  const source = Buffer.from(process.argv[4], "base64").toString("utf8");
  const isProbe = (file) => path.resolve(file) === probe;
  const realExists = host.fileExists.bind(host);
  const realRead = host.readFile.bind(host);
  const realGet = host.getSourceFile.bind(host);
  host.fileExists = (file) => isProbe(file) || realExists(file);
  host.readFile = (file) => (isProbe(file) ? source : realRead(file));
  host.getSourceFile = (file, language, onError, shouldCreate) =>
    isProbe(file)
      ? ts.createSourceFile(file, source, language, true)
      : realGet(file, language, onError, shouldCreate);
  roots = [probe];
}
const program = ts.createProgram({ rootNames: roots, options: parsed.options, host });
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
