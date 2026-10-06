// WEB-1a test support: type-checks every file under src/park (sources and tests) with the web app's
// own tsconfig, through the TypeScript API, so the expectTypeOf checks in the park tests are really
// enforced (Vitest does not evaluate types at runtime). Scoped to park files, so it stays fast.
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
import { PARK_DIR } from "./prototype";

const WEB_DIR = path.resolve(PARK_DIR, "..", "..");

function walk(dir: string): string[] {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return walk(p);
    return /\.(ts|tsx)$/.test(e.name) ? [p] : [];
  });
}

export function parkTypeErrors(): string[] {
  const cfgPath = path.join(WEB_DIR, "tsconfig.json");
  const read = ts.readConfigFile(cfgPath, ts.sys.readFile);
  const parsed = ts.parseJsonConfigFileContent(read.config, ts.sys, WEB_DIR);
  const roots = [...walk(PARK_DIR), ...walk(path.join(WEB_DIR, "test-support", "park"))];
  const program = ts.createProgram({ rootNames: roots, options: parsed.options });
  const parkFiles = new Set(roots.map((r) => path.resolve(r)));
  return ts
    .getPreEmitDiagnostics(program)
    .filter((d) => d.file && parkFiles.has(path.resolve(d.file.fileName)))
    .map((d) => {
      const { line } = d.file?.getLineAndCharacterOfPosition(d.start ?? 0) ?? { line: 0 };
      const rel = path.relative(WEB_DIR, d.file?.fileName ?? "").replaceAll("\\", "/");
      return `${rel}:${line + 1} TS${d.code} ${ts.flattenDiagnosticMessageText(d.messageText, " ")}`;
    });
}
