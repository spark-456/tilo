// W-DEAD-1: conservative candidate audit using the existing TypeScript parser.
// Zero production imports is a review signal, not permission to delete: tests,
// generated assets, entry points and external consumers must be checked separately.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = fileURLToPath(new URL("../src/", import.meta.url));
const files = [];
function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(file);
    else if (/\.(tsx?|css)$/.test(file) && !/\.test\.|\.d\.ts$/.test(file)) files.push(file);
  }
}
walk(root);
const imported = new Set();
for (const file of files.filter((file) => !file.endsWith(".css"))) {
  const source = ts.createSourceFile(
    file,
    fs.readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
  );
  function visit(node) {
    const specifier =
      ts.isImportDeclaration(node) || ts.isExportDeclaration(node)
        ? node.moduleSpecifier
        : ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword
          ? node.arguments[0]
          : undefined;
    if (specifier && ts.isStringLiteral(specifier) && specifier.text.startsWith(".")) {
      const base = path.resolve(path.dirname(file), specifier.text);
      for (const candidate of [
        base,
        `${base}.ts`,
        `${base}.tsx`,
        `${base}.css`,
        path.join(base, "index.ts"),
        path.join(base, "index.tsx"),
      ]) {
        if (fs.existsSync(candidate)) imported.add(candidate);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
}
for (const file of files.filter((file) => !imported.has(file) && !/main\.tsx$/.test(file))) {
  console.log(path.relative(root, file).split(path.sep).join("/"));
}
