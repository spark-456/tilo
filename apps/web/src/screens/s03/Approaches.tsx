import type { PlanApproach } from "@tilo/contracts";
import { useState } from "react";
import { useClient } from "../../api/ClientProvider";
import type { ApproachesResult } from "../../api/client";
import { stagePath } from "../../router";
import { rememberWorld } from "../../world/lastWorld";
import { AppLink } from "../AppLink";
import { Loaded, Primary } from "../FlowShell";
import { useAction, useRemote } from "../remote";
import { BudgetMeter } from "./BudgetMeter";

// biome-ignore format: compact dimension tuple table
const DIMS = [
  ["depth", "Depth"], ["sources", "Sources"], ["parallelism", "Parallelism"],
  ["verification", "Verification"], ["output_format", "Output format"],
] as const;

// The most credits one approval may grant: `caps.run_credits` in config/metering.yaml (PRD 14.1,
// 17.3); services/api answers 422 above it. The web has no config read, so this mirrors it; change
// both together.
export const MAX_BUDGET_CAP_CREDITS = 300;

export const CAP_RULE = `Enter a whole number from 1 to ${MAX_BUDGET_CAP_CREDITS} credits.`;

const formatTime = (t: PlanApproach["time"]): string =>
  t.min_s >= 60 && t.min_s % 60 === 0 && t.max_s % 60 === 0
    ? `${t.min_s / 60}–${t.max_s / 60} min (${t.min_s}–${t.max_s} s)`
    : `${t.min_s}–${t.max_s} s`;

async function loadRecommendation(getApproaches: Promise<ApproachesResult>) {
  const result = await getApproaches;
  const chosen = result.approaches.find((a) => a.id === result.recommended);
  if (result.approaches.length > 0 && !chosen)
    throw new Error("the recommended approach is not in the list");
  return { result, chosen };
}

export function Approaches({ taskId }: { taskId: string }) {
  const client = useClient();
  const [remote, retry] = useRemote("load the approaches", () =>
    loadRecommendation(client.getApproaches(taskId)),
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [capDraft, setCapDraft] = useState<string | null>(null);

  const ready = remote.status === "ready" ? remote.value : null;
  const selected = ready?.result.approaches.find((a) => a.id === selectedId);
  const active = selected ?? ready?.chosen;
  const rawCap = capDraft ?? String(active?.credits.max ?? 0);
  const parsed = Number(rawCap);
  const validCap =
    rawCap.trim() !== "" &&
    Number.isInteger(parsed) &&
    parsed >= 1 &&
    parsed <= MAX_BUDGET_CAP_CREDITS
      ? parsed
      : null;

  const action = useAction("start the run", async () => {
    if (!selected || validCap === null) throw new Error("no approach is selected");
    const { world_id } = await client.approve(taskId, {
      approach_id: selected.id,
      budget_cap: validCap,
    });
    rememberWorld(world_id); // a bare /needs-you or /library shows this run next
    return stagePath(world_id);
  });

  // biome-ignore format: compact JSX
  return (
    <>
      <Loaded what="the approaches" remote={remote} retry={retry} isEmpty={(v) => v.chosen === undefined} empty={<><p>Nothing came back for the approaches. No approach was priced, so nothing was started.</p><button type="button" className="secondary" onClick={retry}>Try again</button> <AppLink to="/" className="secondary">Describe the task again</AppLink></>}>
        {({ result, chosen }) => {
          const diff = DIMS.filter(([k]) => new Set(result.approaches.map((a) => a.dimensions[k])).size > 1);
          const dims = diff.length > 0 ? diff : DIMS;
          return (
            <div className="s03-approaches">
              <p className="flow-summary">Compare priced approaches and confirm your budget cap. Recommended: {chosen?.label}.</p>
              <div className="approach-list" data-testid="approach-list">
                {result.approaches.map((a) => (
                  <article key={a.id} className="approach-card" data-testid={`approach-card-${a.id}`} data-selected={a.id === selectedId ? "true" : "false"}>
                    <div className="approach-head">
                      <button type="button" className="secondary approach-select" data-testid={`select-approach-${a.id}`} aria-pressed={a.id === selectedId} onClick={() => { setSelectedId(a.id); setCapDraft(String(a.credits.max)); }}>{a.label}</button>
                      {a.id === result.recommended && <span className="btag" data-testid="recommended-badge">Recommended</span>}
                    </div>
                    <p className="approach-summary">{a.summary}</p>
                    <p className="approach-meta" data-testid="approach-ranges">{`Time: ${formatTime(a.time)} · Credits: ${a.credits.min}–${a.credits.max} credits`}</p>
                    <p className="approach-meta" data-testid="approach-dimensions">{dims.map(([k, label]) => `${label}: ${a.dimensions[k]}`).join(" · ")}</p>
                    <p className="approach-meta" data-testid="approach-risks">{`Risks: ${a.risks.length > 0 ? a.risks.join("; ") : "None"}`}</p>
                    <p className="approach-meta" data-testid="approach-skips">{`Skips: ${a.skips.length > 0 ? a.skips.join("; ") : "Nothing"}`}</p>
                  </article>
                ))}
              </div>
              <label className="budget-cap-field" htmlFor="budget-cap-input">
                <span>Budget cap (credits)</span>
                <input id="budget-cap-input" data-testid="budget-cap-input" type="number" min={1} max={MAX_BUDGET_CAP_CREDITS} step={1} aria-invalid={validCap === null} aria-describedby="budget-cap-hint" value={rawCap} onChange={(e) => setCapDraft(e.target.value)} />
              </label>
              {active && <BudgetMeter min={active.credits.min} max={active.credits.max} cap={validCap} />}
              <output id="budget-cap-hint" className="budget-cap-hint" data-testid="budget-cap-hint">{validCap === null ? CAP_RULE : ""}</output>
              <p className="flow-detail" data-testid="budget-line">{validCap === null ? "The cost is shown once the cap is valid." : `This run can use up to ${validCap} credits (about US$${(validCap * result.credit_usd).toFixed(2)}). You can pause it any time.`}</p>
            </div>
          );
        }}
      </Loaded>
      <Primary label="Start this approach" action={action} disabled={!selected || validCap === null} />
    </>
  );
}
