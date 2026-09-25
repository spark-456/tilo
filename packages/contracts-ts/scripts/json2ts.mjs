// Generation tooling for @tilo/contracts (not generated). Reads the bundled JSON Schema that
// scripts/contracts_codegen.py builds on stdin and writes TypeScript for every $defs entry to
// stdout with json-schema-to-typescript. Run it through `just contracts-gen`, not by hand.
import { compile } from "json-schema-to-typescript";

let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;

const ts = await compile(JSON.parse(input), "TiloContracts", {
  bannerComment: "",
  additionalProperties: false,
  unreachableDefinitions: true,
  maxItems: -1,
  strictIndexSignatures: false,
  format: true,
  style: { endOfLine: "lf", printWidth: 100, singleQuote: false, trailingComma: "all" },
});
process.stdout.write(ts);
