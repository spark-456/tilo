import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import { HttpClient, TiloApiError, displayApiError } from "./http";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");

// Contract-fixed refusals propagated through connector/model-key RPCs or returned in
// page data. Keep the wire words and their contract together; never change contracts
// to make this coverage check pass. The enum assertion also catches new fixed codes.
const contractCodes = [
  [
    "contracts/meeting_host_rpc.schema.json",
    ["$defs", "error", "properties", "error"],
    "unauthenticated forbidden invalid_request not_configured start_again not_granted wrong_account key_refused",
  ],
  [
    "contracts/org_model_key.schema.json",
    ["$defs", "error_code"],
    "owner_only reauth_required confirm_required key_refused invalid_body rate_limited not_configured unavailable",
  ],
  [
    "contracts/org_model_key.schema.json",
    ["$defs", "owner_last_error"],
    "invalid_key quota rate_limited unreachable not_configured",
  ],
  [
    "contracts/model_call_rpc.schema.json",
    ["$defs", "error", "properties", "error"],
    "unauthenticated forbidden invalid_request not_configured no_key unverified invalid_key rate_limited quota unreachable",
  ],
  [
    "contracts/mcp_tools.schema.json",
    ["$defs", "tool_refusal", "properties", "error"],
    "invalid_arguments not_found insufficient_scope not_answerable_here already_resolved busy rate_limited over_cap rejected_by_intake unavailable",
  ],
  ["contracts/mcp_tools.schema.json", ["$defs", "withheld_reason"], "not_text too_large"],
  [
    "contracts/meeting_voice_meter.schema.json",
    ["$defs", "error", "properties", "error"],
    "unauthenticated forbidden invalid_request not_configured not_attending no_hold key_used",
  ],
  [
    "contracts/meeting_voice_meter.schema.json",
    ["$defs", "reserve_answer", "properties", "reason"],
    "capped replay_only unavailable hold_open meeting_limit",
  ],
] as const;

function pythonSources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? pythonSources(path) : entry.name.endsWith(".py") ? [path] : [];
  });
}

it("X-APIERR-2 maps every API source and contract-fixed refusal to a sentence", async () => {
  const origins = new Map<string, Set<string>>();
  const add = (code: string, file: string) => {
    const files = origins.get(code) ?? new Set<string>();
    files.add(file);
    origins.set(code, files);
  };
  for (const file of pythonSources(join(root, "services/api/src"))) {
    const source = readFileSync(file, "utf8");
    // HTTPException details, JSON response codes/reasons, and the route writers'
    // typed refusals (the latter become detail or reason at their HTTP boundary).
    for (const pattern of [
      /(?:detail\s*=|["'](?:code|reason|refusal)["']\s*:)\s*["']([a-z][a-z0-9_-]*)["']/g,
      /AnswerResult\("rejected",\s*"([a-z][a-z0-9_-]*)"/g,
      /(?:Refusal|ShareRefused|RoleChangeRefused)\([^\n]*?["']([a-z][a-z0-9_-]*)["']/g,
    ]) {
      for (const match of source.matchAll(pattern)) add(match[1] ?? "", file);
    }
    // Access middleware uses positional arguments for both its detail and code.
    for (const line of source.split("\n").filter((line) => line.includes("_refusal("))) {
      for (const match of line.matchAll(/["']([a-z][a-z0-9_-]*)["']/g)) add(match[1] ?? "", file);
    }
  }
  // meeting_host.py propagates MeetingHostRefused.rule from this connector draft
  // validator (services/connectors/tests/API_FR_MTG_09.md, MH-01..MH-07).
  const hostSource = "services/connectors/src/tilo_connectors/meeting_host.py";
  for (const match of readFileSync(join(root, hostSource), "utf8").matchAll(
    /MeetingHostRefused\("(MH-\d{2})"/g,
  ))
    add(match[1] ?? "", hostSource);
  for (const [file, path, words] of contractCodes) {
    let value: unknown = JSON.parse(readFileSync(join(root, file), "utf8"));
    for (const key of path) value = (value as Record<string, unknown>)[key];
    const codes = words.split(" ");
    expect((value as { enum: string[] }).enum, file).toEqual(codes);
    for (const code of codes) add(code, file);
  }
  expect(origins.has("app_check_required")).toBe(true);
  expect(origins.has("declaration_required")).toBe(false); // OPEN-ACCESS: the sign-up question is gone
  expect(origins.has("invalid_option")).toBe(true);
  expect(origins.has("MH-02")).toBe(true);
  for (const [code, files] of origins) {
    const context = `${code}: ${[...files].join(", ")}`;
    const words = displayApiError(new TiloApiError("private server text", 418, false, false, code));
    // An unmapped code would receive this generic fallback at an unknown status.
    expect(words, context).not.toBe("Tilo had a problem on its side.");
    expect(words, context).toMatch(/^[A-Z].*[.!]$/);
    expect(words, context).not.toBe(code);
    expect(words, context).not.toMatch(/[_<>]/);
    for (const body of [
      { code },
      { detail: code },
      { reason: code },
      { error: code },
      { detail: { code } },
      ...(code.startsWith("MH-") ? [{ rule: code }] : []),
    ]) {
      const client = new HttpClient({
        baseUrl: "https://api.test",
        fetch: async () => new Response(JSON.stringify(body), { status: 503 }),
      });
      const error = await client.getJson("/costs").catch((failure: unknown) => failure);
      expect(error, context).toBeInstanceOf(TiloApiError);
      expect(displayApiError(error), context).toBe(words);
    }
  }
});
