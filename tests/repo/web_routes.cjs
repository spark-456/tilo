// ROUTE-AUDIT-1: inspect calls with TypeScript's parser, including imported URL builders.
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");
const root = path.resolve(__dirname, "../..");
const ts = createRequire(path.join(root, "apps/web/package.json"))("typescript");
function files(dir) {
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .flatMap((e) =>
      e.isDirectory()
        ? files(path.join(dir, e.name))
        : /\.[tj]sx?$/.test(e.name) && !/\.test\./.test(e.name)
          ? [path.join(dir, e.name)]
          : [],
    );
}
const probe = process.argv[2];
const program = ts.createProgram(
  probe ? [path.resolve(probe)] : files(path.join(root, "apps/web/src")),
  { allowJs: true },
);
const checker = program.getTypeChecker();
const sources = program
  .getSourceFiles()
  .filter((s) =>
    probe
      ? path.resolve(s.fileName) === path.resolve(probe)
      : /apps\/web\/src\//.test(s.fileName.replaceAll("\\", "/")),
  );
const calls = [];
function walk(n, visit) {
  visit(n);
  ts.forEachChild(n, (c) => walk(c, visit));
}
for (const s of sources)
  walk(s, (n) => {
    if (ts.isCallExpression(n)) calls.push(n);
  });
function symbol(n) {
  let s = ts.isShorthandPropertyAssignment(n.parent)
    ? checker.getShorthandAssignmentValueSymbol(n.parent)
    : checker.getSymbolAtLocation(n);
  if (s && s.flags & ts.SymbolFlags.Alias) s = checker.getAliasedSymbol(s);
  return s;
}
const unknown = "{param}";
function combine(a, b) {
  return a.flatMap((x) => b.map((y) => String(x) + String(y)));
}
function returns(fn) {
  if (!fn.body) return [];
  if (!ts.isBlock(fn.body)) return [fn.body];
  const result = [];
  function visit(n) {
    if (ts.isReturnStatement(n) && n.expression) result.push(n.expression);
    else if (!ts.isFunctionLike(n)) ts.forEachChild(n, visit);
  }
  ts.forEachChild(fn.body, visit);
  return result;
}
function value(n, env = new Map(), seen = new Set()) {
  if (!n || seen.has(n)) return [unknown];
  const visited = new Set(seen).add(n);
  const read = (x) => value(x, env, visited);
  if (ts.isStringLiteralLike(n)) return [n.text];
  if (ts.isParenthesizedExpression(n) || ts.isAsExpression(n) || ts.isAwaitExpression(n))
    return read(n.expression);
  if (ts.isConditionalExpression(n)) {
    if (ts.isIdentifier(n.condition) && env.has(symbol(n.condition)))
      return env.get(symbol(n.condition)).flatMap((v) => read(v === "" ? n.whenFalse : n.whenTrue));
    return [...read(n.whenTrue), ...read(n.whenFalse)];
  }
  if (ts.isTemplateExpression(n)) {
    let parts = [n.head.text];
    for (const span of n.templateSpans)
      parts = combine(combine(parts, read(span.expression)), [span.literal.text]);
    return parts;
  }
  if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.PlusToken)
    return combine(read(n.left), read(n.right));
  if (ts.isObjectLiteralExpression(n)) {
    let objects = [{}];
    for (const p of n.properties) {
      if (!ts.isPropertyAssignment(p) && !ts.isShorthandPropertyAssignment(p)) continue;
      const key = p.name.getText().replaceAll('"', "");
      objects = objects.flatMap((o) =>
        read(p.initializer ?? p.name).map((v) => ({ ...o, [key]: v })),
      );
    }
    return objects;
  }
  if (ts.isPropertyAccessExpression(n)) {
    const got = read(n.expression)
      .map((v) => v?.[n.name.text])
      .filter((v) => v !== undefined);
    if (got.length) return got;
    // A decision URL is stored in a Map record before postJson(target.path).
    if (n.name.text === "path") {
      const paths = [];
      walk(n.getSourceFile(), (p) => {
        if (ts.isPropertyAssignment(p) && p.name.getText() === "path")
          paths.push(...read(p.initializer));
        if (ts.isShorthandPropertyAssignment(p) && p.name.text === "path")
          paths.push(...read(p.name));
      });
      return paths.length ? paths : [unknown];
    }
  }
  if (ts.isIdentifier(n)) {
    const s = symbol(n);
    if (env.has(s)) return env.get(s);
    const d = s?.valueDeclaration;
    if (d && ts.isVariableDeclaration(d)) return read(d.initializer);
    if (d && ts.isBindingElement(d)) {
      const v = read(d.parent.parent.initializer);
      return v.map((o) => o[d.propertyName?.getText() ?? d.name.getText()] ?? unknown);
    }
    if (d && ts.isParameter(d)) {
      // `["a", "b"].map((x) => ...)`: x is each string of the array literal.
      const fn0 = d.parent;
      const call0 = fn0?.parent;
      if (
        call0 &&
        ts.isCallExpression(call0) &&
        ts.isPropertyAccessExpression(call0.expression) &&
        call0.expression.name.text === "map" &&
        ts.isArrayLiteralExpression(call0.expression.expression) &&
        fn0.parameters.indexOf(d) === 0 &&
        call0.expression.expression.elements.every(ts.isStringLiteralLike)
      )
        return call0.expression.expression.elements.map((e) => e.text);
      if (d.type && ts.isUnionTypeNode(d.type) && d.type.types.every(ts.isLiteralTypeNode))
        return d.type.types.flatMap((t) => read(t.literal));
      // String identifiers represent route parameters, but a path is resolved from callers.
      if (d.name.getText() === "path") {
        const fn = d.parent;
        const fnSymbol = symbol(fn.name ?? fn.parent.name);
        const index = fn.parameters.indexOf(d);
        const values = calls
          .filter((c) => symbol(c.expression) === fnSymbol)
          .flatMap((c) => read(c.arguments[index]));
        return values.length ? values : [unknown];
      }
    }
  }
  if (ts.isCallExpression(n)) {
    if (["encodeURIComponent", "e"].includes(n.expression.getText())) return [unknown];
    const d = symbol(n.expression)?.valueDeclaration;
    const fn = d && ts.isVariableDeclaration(d) ? d.initializer : d;
    if (fn && ts.isFunctionLike(fn)) {
      const bound = new Map(env);
      fn.parameters.forEach((p, i) =>
        bound.set(symbol(p.name), n.arguments[i] ? read(n.arguments[i]) : [""]),
      );
      const results = returns(fn).flatMap((r) => value(r, bound, visited));
      return results.length ? results : [unknown];
    }
  }
  return [unknown];
}
const helpers = {
  getJson: "GET",
  getBlob: "GET",
  postJson: "POST",
  post: "POST",
  putJson: "PUT",
  deleteJson: "DELETE",
  // A capability probe for a POST route (OPTIONS answers 405 when it is registered): audited as the POST it probes.
  hasPostRoute: "POST",
};
const routes = [];
const errors = [];
for (const c of calls) {
  const source = c.getSourceFile();
  const file = path.relative(root, source.fileName).replaceAll("\\", "/");
  if (!probe && !/^apps\/web\/src\/(api|park\/api)\//.test(file)) continue;
  const name = ts.isPropertyAccessExpression(c.expression)
    ? c.expression.name.text
    : c.expression.getText();
  if (!Object.hasOwn(helpers, name) && !["request", "sendJson", "fetch", "fetchFn"].includes(name))
    continue;
  if (
    ["post", "request"].includes(name) &&
    (!ts.isPropertyAccessExpression(c.expression) ||
      c.expression.expression.kind !== ts.SyntaxKind.ThisKeyword)
  )
    continue;
  // HttpClient's injected fetch transport is audited at its request callers.
  if (
    file === "apps/web/src/api/http.ts" &&
    name === "fetch" &&
    c.arguments[0]?.getText() === "url"
  )
    continue;
  // Generic transport implementation: its callers supply the audited path and method.
  let owner = c.parent;
  while (owner && !ts.isMethodDeclaration(owner)) owner = owner.parent;
  if (
    file === "apps/web/src/api/http.ts" &&
    owner &&
    [
      "request",
      "getJson",
      "getBlob",
      "readPerson",
      "postJson",
      "putJson",
      "deleteJson",
      "sendJson",
      "post",
      "hasPostRoute",
    ].includes(owner.name.getText())
  )
    continue;
  const line = source.getLineAndCharacterOfPosition(c.getStart()).line + 1;
  let methods = [helpers[name] ?? "GET"];
  let arg = c.arguments[0];
  if (name === "sendJson") {
    methods = value(arg);
    arg = c.arguments[1];
  }
  if (["request", "fetch", "fetchFn"].includes(name))
    methods = value(c.arguments[1]).map((o) => o?.method ?? "GET");
  const paths = value(arg);
  let pairs = [...new Set(methods)].flatMap((method) =>
    [...new Set(paths)].map((url) => ({ method, url })),
  );
  // Preserve method/path correlation in `const {method, path} = requestOf(op)`.
  if (name === "sendJson") {
    const md = symbol(c.arguments[0])?.valueDeclaration;
    const pd = symbol(c.arguments[1])?.valueDeclaration;
    if (md && pd && ts.isBindingElement(md) && ts.isBindingElement(pd) && md.parent === pd.parent)
      pairs = value(md.parent.parent.initializer).map((o) => ({ method: o.method, url: o.path }));
  }
  for (const { method, url } of pairs) {
    if (
      typeof url !== "string" ||
      !url.startsWith("/") ||
      !/^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$/.test(method)
    )
      errors.push(
        `${file}:${line}: unresolved ${name}(${arg?.getText()}) method=${method} path=${url}`,
      );
    else routes.push({ method, path: url.split("?")[0], file, line });
  }
}
process.stdout.write(JSON.stringify({ routes, errors }));
