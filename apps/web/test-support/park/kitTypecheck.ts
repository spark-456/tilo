// WEB-1c test support: type-checks apps/web/src/park/engines/kit.ts with the web app's own tsconfig (strict,
// noUncheckedIndexedAccess, exactOptionalPropertyTypes) through the TypeScript API, counts its escape hatches
// (`any`, ts directives), and compiles a small in-memory consumer ("probe") against it so the exported
// signatures and the exact member set are pinned at type level. Vitest does not evaluate types at runtime.
// Separate from engineTypecheck.ts (WEB-1b) so that file and its tests stay as they are.
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
import { ENGINES_DIR, WEB_DIR } from "./engineProto";

export const KIT_FILE = path.join(ENGINES_DIR, "kit.ts");
const rel = (f: string) => path.relative(WEB_DIR, f).replaceAll("\\", "/");

function options(): ts.CompilerOptions {
  const read = ts.readConfigFile(path.join(WEB_DIR, "tsconfig.json"), ts.sys.readFile);
  return ts.parseJsonConfigFileContent(read.config, ts.sys, WEB_DIR).options;
}

export function kitExists(): boolean {
  return fs.existsSync(KIT_FILE);
}

function messages(program: ts.Program, only: Set<string>): string[] {
  return ts
    .getPreEmitDiagnostics(program)
    .filter((d) => d.file && only.has(path.resolve(d.file.fileName)))
    .map((d) => {
      const { line } = d.file?.getLineAndCharacterOfPosition(d.start ?? 0) ?? { line: 0 };
      return `${rel(d.file?.fileName ?? "")}:${line + 1} TS${d.code} ${ts.flattenDiagnosticMessageText(d.messageText, " ")}`;
    });
}

/** Compile errors in kit.ts itself (and nothing else); empty when the file is missing. */
export function kitTypeErrors(): string[] {
  if (!kitExists()) return [];
  const program = ts.createProgram({ rootNames: [KIT_FILE], options: options() });
  return messages(program, new Set([path.resolve(KIT_FILE)]));
}

/** `any` used as a type in kit.ts (an AST keyword, so a string or a comment never counts). */
export function kitAnyUses(): number[] {
  if (!kitExists()) return [];
  const sf = ts.createSourceFile(
    KIT_FILE,
    fs.readFileSync(KIT_FILE, "utf8"),
    ts.ScriptTarget.ES2022,
    true,
  );
  const out: number[] = [];
  const visit = (n: ts.Node) => {
    if (n.kind === ts.SyntaxKind.AnyKeyword)
      out.push(sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1);
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

/** `@ts-ignore`, `@ts-nocheck`, `@ts-expect-error` lines in kit.ts. */
export function kitDirectives(): string[] {
  if (!kitExists()) return [];
  return fs
    .readFileSync(KIT_FILE, "utf8")
    .split(/\r?\n/)
    .map((line, i) => ({ line, n: i + 1 }))
    .filter((l) => /@ts-(?:ignore|nocheck|expect-error)/.test(l.line))
    .map((l) => `${rel(KIT_FILE)}:${l.n} ${l.line.trim()}`);
}

/**
 * Compile `source` as a file next to kit.ts (so it can `import "./kit"`), without writing it to disk.
 * Returns the errors in the probe only. The probe may use `@ts-expect-error`: an unused one is an error
 * (TS2578), which is how "this call must NOT compile" is pinned.
 */
export function probeErrors(source: string): string[] {
  const probe = path.join(ENGINES_DIR, "__kit_probe__.ts");
  const key = (f: string) => path.resolve(f);
  const opts = options();
  const host = ts.createCompilerHost(opts);
  const realExists = host.fileExists.bind(host);
  const realRead = host.readFile.bind(host);
  const realGet = host.getSourceFile.bind(host);
  host.fileExists = (f) => key(f) === key(probe) || realExists(f);
  host.readFile = (f) => (key(f) === key(probe) ? source : realRead(f));
  host.getSourceFile = (f, lang, onError, shouldCreate) =>
    key(f) === key(probe)
      ? ts.createSourceFile(f, source, lang, true)
      : realGet(f, lang, onError, shouldCreate);
  const program = ts.createProgram({ rootNames: [probe], options: opts, host });
  return messages(program, new Set([key(probe)]));
}
