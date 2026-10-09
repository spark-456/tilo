// WEB-1b test support: type-checks the engine sources under src/park/engines with the web app's own
// tsconfig (strict, noUncheckedIndexedAccess, exactOptionalPropertyTypes) through the TypeScript API, and
// counts the escape hatches (`any`, ts directives). Vitest does not evaluate types at runtime.
// Scoped to the engine files (not their tests), so it stays quick.
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
import { ENGINES_DIR, WEB_DIR } from "./engineProto";
import { parkTypeErrors } from "./typecheck";

export function engineSources(): string[] {
  if (!fs.existsSync(ENGINES_DIR)) return [];
  const walk = (dir: string): string[] =>
    fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) return walk(p);
      return /\.(ts|tsx)$/.test(e.name) && !/\.test\.tsx?$/.test(e.name) ? [p] : [];
    });
  return walk(ENGINES_DIR);
}

export async function engineTypeErrors(): Promise<string[]> {
  const roots = engineSources();
  if (roots.length === 0) return [];
  const prefixes = roots.map((file) => `${path.relative(WEB_DIR, file).replaceAll("\\", "/")}:`);
  return (await parkTypeErrors()).filter((error) =>
    prefixes.some((prefix) => error.startsWith(prefix)),
  );
}

/** `any` used as a type (a keyword node in the AST, so a string or a comment never counts), per file. */
export function anyUses(): { file: string; line: number }[] {
  const out: { file: string; line: number }[] = [];
  for (const f of engineSources()) {
    const sf = ts.createSourceFile(f, fs.readFileSync(f, "utf8"), ts.ScriptTarget.ES2022, true);
    const visit = (n: ts.Node) => {
      if (n.kind === ts.SyntaxKind.AnyKeyword) {
        const { line } = sf.getLineAndCharacterOfPosition(n.getStart(sf));
        out.push({ file: path.relative(WEB_DIR, f).replaceAll("\\", "/"), line: line + 1 });
      }
      ts.forEachChild(n, visit);
    };
    visit(sf);
  }
  return out;
}

/** `// @ts-ignore`, `@ts-nocheck`, `@ts-expect-error` lines (comments, so a text search). */
export function tsDirectives(): string[] {
  return engineSources().flatMap((f) =>
    fs
      .readFileSync(f, "utf8")
      .split(/\r?\n/)
      .map((line, i) => ({ line, n: i + 1 }))
      .filter((l) => /@ts-(?:ignore|nocheck|expect-error)/.test(l.line))
      .map((l) => `${path.relative(WEB_DIR, f).replaceAll("\\", "/")}:${l.n} ${l.line.trim()}`),
  );
}
