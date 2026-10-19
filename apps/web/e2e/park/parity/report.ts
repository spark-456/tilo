// WEB-PARITY: the report (report.json and a scannable report.md) for design-critic.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { PAGES, THEMES, VIEWPORTS } from "./pages";
import type { StyleDiff } from "./styles";

export interface RegionResult {
  name: string;
  pct: number | null;
  mismatched: number;
  total: number;
  note?: string | undefined;
  file?: string | undefined;
}
export interface CaptureResult {
  page: string;
  viewport: string;
  theme: string;
  status: "ok" | "route missing" | "error";
  error?: string | undefined;
  pct?: number;
  mismatched?: number;
  total?: number;
  designSize?: string;
  oursSize?: string;
  sizeMismatch?: boolean;
  regions: RegionResult[];
  styleDiffs?: StyleDiff[];
  consoleErrors: string[];
  /** Folder relative to the report root. */
  dir: string;
}

const pct = (n: number | null | undefined) => (n == null ? "n/a" : `${n.toFixed(2)}%`);
const key = (c: CaptureResult) => `${c.page}|${c.viewport}|${c.theme}`;

function cell(c: CaptureResult | undefined): string {
  if (!c) return "not run";
  if (c.status !== "ok") return c.status;
  return (
    pct(c.pct) +
    (c.sizeMismatch ? " (size differs)" : "") +
    (c.consoleErrors.length ? " (console errors)" : "")
  );
}

export function renderMarkdown(results: CaptureResult[]): string {
  const by = new Map(results.map((c) => [key(c), c]));
  const cols = VIEWPORTS.flatMap((v) => THEMES.map((t) => ({ v: v.name, t })));
  const out = [
    "# Park pixel-parity report",
    "",
    "Diff % = mismatched pixels / total (pixelmatch, threshold 0.1).",
    "",
  ];
  out.push(`| Page | ${cols.map((c) => `${c.v} ${c.t}`).join(" | ")} |`);
  out.push(`| --- | ${cols.map(() => "---").join(" | ")} |`);
  const ran = new Set(results.map((c) => c.page));
  for (const p of PAGES.filter((p) => ran.has(p.name))) {
    out.push(
      `| ${p.name} | ${cols.map((c) => cell(by.get(`${p.name}|${c.v}|${c.t}`))).join(" | ")} |`,
    );
  }
  const ok = results.filter((c) => c.status === "ok").sort((a, b) => (b.pct ?? 0) - (a.pct ?? 0));
  const bad = results.filter((c) => c.status !== "ok");
  const withErrors = results.filter((c) => c.consoleErrors.length > 0);
  out.push(
    "",
    `Captured ${ok.length}, route missing ${bad.filter((c) => c.status === "route missing").length}, error ${bad.filter((c) => c.status === "error").length}, with console errors (ours) ${withErrors.length}.`,
  );
  for (const c of withErrors) {
    out.push(
      "",
      `### Console errors: ${c.page} ${c.viewport} ${c.theme}`,
      ...c.consoleErrors.map((e) => `- ${e}`),
    );
  }
  for (const c of bad)
    out.push(
      "",
      `- ${c.page} ${c.viewport} ${c.theme}: ${c.status}${c.error ? ` (${c.error})` : ""}`,
    );
  out.push("", "## Captures, worst first");
  for (const c of ok) {
    out.push("", `### ${c.page} ${c.viewport} ${c.theme}: ${pct(c.pct)}`, "");
    out.push(
      `Design ${c.designSize}, ours ${c.oursSize}${c.sizeMismatch ? " **SIZE MISMATCH** (padded with magenta to the larger)" : ""}.`,
    );
    out.push(
      `Images: [design](${c.dir}/design.png), [ours](${c.dir}/ours.png), [diff-full](${c.dir}/diff-full.png).`,
      "",
    );
    const sd = c.styleDiffs ?? [];
    out.push(
      `Computed-style differences: ${sd.length}${sd.length > 40 ? " (first 40 here, all in report.json)" : ""}.`,
      "",
    );
    if (sd.length > 0) {
      out.push(
        "| Region | Element | Property | Design | Ours |",
        "| --- | --- | --- | --- | --- |",
      );
      for (const s of sd.slice(0, 40))
        out.push(`| ${s.region} | ${s.element} | ${s.prop} | ${s.design} | ${s.ours} |`);
      out.push("");
    }
    out.push("| Region | Diff % | Note | Image |", "| --- | --- | --- | --- |");
    for (const r of [...c.regions].sort((a, b) => (b.pct ?? -1) - (a.pct ?? -1))) {
      out.push(
        `| ${r.name} | ${pct(r.pct)} | ${r.note ?? ""} | ${r.file ? `[diff](${c.dir}/${r.file})` : ""} |`,
      );
    }
  }
  return `${out.join("\n")}\n`;
}

export function writeReport(
  root: string,
  results: CaptureResult[],
  meta: Record<string, unknown>,
): void {
  mkdirSync(root, { recursive: true });
  writeFileSync(join(root, "report.json"), `${JSON.stringify({ ...meta, results }, null, 2)}\n`);
  writeFileSync(join(root, "report.md"), renderMarkdown(results));
}
