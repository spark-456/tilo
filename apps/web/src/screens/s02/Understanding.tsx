import type { Brief, DeliverableFormat } from "@tilo/contracts";
import { useState } from "react";
import { useClient } from "../../api/ClientProvider";
import type { IntakeFileStatus, IntakeResult } from "../../api/client";
import { Loaded, Primary } from "../FlowShell";
import { type Remote, useAction } from "../remote";

// biome-ignore format: compact tuple table
const FIELDS = [["goal", "Goal"], ["deliverables", "Deliverables"], ["audience", "Audience"], ["deadline", "Deadline"], ["constraints", "Constraints"], ["sources", "Sources"], ["sensitivity", "Sensitivity"]] as const;
type BriefField = (typeof FIELDS)[number][0];

// biome-ignore format: compact enum sets from contracts/common.schema.json
const DATA_CLASSES = ["personal", "business", "public"] as const;
// biome-ignore format: compact enum sets from contracts/common.schema.json
const FORMATS = new Set<string>(["pdf", "pptx", "docx", "xlsx", "csv", "markdown", "google_slides", "google_docs", "google_sheets", "email", "in_app"]);

const intakes = new Map<string, IntakeResult>();
export const rememberIntake = (i: IntakeResult): void => void intakes.set(i.task_id, i);

// biome-ignore format: compact helpers
const toDraft = (b: Brief): Record<BriefField, string> => ({
  goal: b.goal, audience: b.audience, deadline: b.deadline ?? "", sensitivity: b.sensitivity,
  deliverables: b.deliverables.map((d) => `${d.title} (${d.format})`).join(", "),
  constraints: b.constraints.join(", "), sources: b.sources.map((s) => s.label ?? s.ref).join(", "),
});
// biome-ignore format: compact csv parser
const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

// biome-ignore format: compact validator for brief.schema.json invariants
function invalidFields(b: Brief, d: Record<BriefField, string>): Set<BriefField> {
  const bad = new Set<BriefField>();
  if (!d.goal.trim() || d.goal.trim().length > 500) bad.add("goal");
  if (!d.audience.trim() || d.audience.trim().length > 200) bad.add("audience");
  if (d.deadline.trim() && !/^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.test(d.deadline.trim())) bad.add("deadline");
  if (!(DATA_CLASSES as readonly string[]).includes(d.sensitivity)) bad.add("sensitivity");
  const delivs = csv(d.deliverables);
  const fb = b.deliverables[0]?.format ?? "pdf";
  const delivBad = delivs.length === 0 || delivs.length > 10 || delivs.some((s) => {
    const m = /^(.+?)\s*\(([^)]+)\)$/.exec(s);
    const title = m ? (m[1]?.trim() ?? "") : s;
    const fmt = m ? (m[2]?.trim().toLowerCase() ?? "") : fb;
    return !title || title.length > 120 || !FORMATS.has(fmt);
  });
  if (delivBad) bad.add("deliverables");
  return bad;
}

// biome-ignore format: compact brief edit parser preserving schema invariants
function toBriefEdits(b: Brief, draft: Record<BriefField, string>, bad: Set<BriefField>): Partial<Brief> {
  const init = toDraft(b);
  const edits: Partial<Brief> = {};
  if (draft.goal !== init.goal && !bad.has("goal")) edits.goal = draft.goal.trim();
  if (draft.deliverables !== init.deliverables && !bad.has("deliverables")) {
    const fb = b.deliverables[0]?.format ?? "pdf";
    const items = csv(draft.deliverables).map((s, i) => {
      const m = /^(.+?)\s*\(([^)]+)\)$/.exec(s);
      const fallbackFmt = b.deliverables[i]?.format ?? fb;
      return m ? { title: m[1]?.trim() ?? s, format: m[2]?.trim().toLowerCase() as DeliverableFormat } : { title: s, format: fallbackFmt };
    });
    if (items[0]) edits.deliverables = [items[0], ...items.slice(1)];
  }
  if (draft.audience !== init.audience && !bad.has("audience")) edits.audience = draft.audience.trim();
  if (draft.deadline !== init.deadline && !bad.has("deadline")) edits.deadline = draft.deadline.trim() || null;
  if (draft.constraints !== init.constraints) edits.constraints = csv(draft.constraints);
  if (draft.sources !== init.sources) {
    edits.sources = csv(draft.sources).map((item, i) => {
      const orig = b.sources[i];
      if (!orig) return { kind: "web", ref: item };
      return orig.label !== undefined ? { ...orig, label: item } : { kind: orig.kind, ref: item };
    });
  }
  if (draft.sensitivity !== init.sensitivity && !bad.has("sensitivity")) edits.sensitivity = draft.sensitivity as Brief["sensitivity"];
  return edits;
}

// biome-ignore format: compact status formatter
const fileStatus = (f: IntakeFileStatus): string =>
  f.safety_flagged ? `Flagged: ${f.reason ?? ""}`.trim() : f.status === "failed" ? `Couldn't read: ${f.reason ?? ""}`.trim() : f.status;

// biome-ignore format: compact component
export function Understanding({ taskId }: { taskId: string }) {
  const client = useClient();
  const [, setTick] = useState(0);
  const intake = intakes.get(taskId) ?? null;
  const remote: Remote<IntakeResult | null> = { status: "ready", value: intake };
  const [draft, setDraft] = useState<Record<BriefField, string> | null>(() => (intake ? toDraft(intake.brief) : null));
  const activeDraft = draft ?? (intake ? toDraft(intake.brief) : null);
  const bad = intake && activeDraft ? invalidFields(intake.brief, activeDraft) : new Set<BriefField>();
  const questions = intake ? intake.questions.slice(0, 3) : [];
  const [answers, setAnswers] = useState<Record<number, string | null>>({});
  const [skipped, setSkipped] = useState<Record<number, boolean>>({});
  const pick = (i: number, val: string | null, isSkip: boolean) => { setSkipped((m) => ({ ...m, [i]: isSkip })); setAnswers((a) => ({ ...a, [i]: val })); };
  const action = useAction("confirm the brief", async () => {
    if (!intake || !activeDraft) throw new Error("no brief is loaded");
    const qAnswers = questions.map((q, i) => ({ field: q.field, answer: skipped[i] ? null : (answers[i] ?? null) }));
    await client.answerQuestions(taskId, qAnswers, toBriefEdits(intake.brief, activeDraft, bad));
    return `/task/${encodeURIComponent(taskId)}/approaches`;
  });

  // biome-ignore format: compact JSX
  return (
    <div className="s02-understanding">
      <Loaded what="the brief" remote={remote} retry={() => setTick((n) => n + 1)} isEmpty={(v) => v === null}>
        {(loaded) => !loaded || !activeDraft ? null : (
          <>
            <p className="flow-summary">Review the extracted brief and clarifying questions.</p>
            <div className="brief-chips" data-testid="brief-chips">
              {FIELDS.map(([f, label]) => (
                <label key={f} htmlFor={`brief-${f}`} className="brief-chip" data-testid={`brief-chip-${f}`}>
                  <span>{label}</span>
                  {f === "sensitivity" ? (
                    <select id={`brief-${f}`} aria-invalid={bad.has(f) ? "true" : undefined} value={activeDraft[f]} onChange={(e) => setDraft({ ...activeDraft, [f]: e.target.value })}>
                      {DATA_CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  ) : (
                    <input id={`brief-${f}`} type="text" aria-invalid={bad.has(f) ? "true" : undefined} value={activeDraft[f]} onChange={(e) => setDraft({ ...activeDraft, [f]: e.target.value })} />
                  )}
                </label>
              ))}
            </div>
            {loaded.files.length > 0 && (
              <ul className="brief-list" data-testid="intake-files" aria-label="Files">
                {loaded.files.map((f) => <li key={f.name} data-testid="intake-file">{`${f.name}: ${fileStatus(f)}`}</li>)}
              </ul>
            )}
            {loaded.brief.applied_preferences.length > 0 && (
              <ul className="brief-list" data-testid="applied-preferences" aria-label="Preferences">
                {loaded.brief.applied_preferences.map((p) => (
                  <li key={`${p.field}-${p.citation.ref}`} data-testid="applied-preference">{`Using your preference: ${p.value} (${p.citation.ref}, ${p.citation.recorded_at})`}</li>
                ))}
              </ul>
            )}
            {questions.length > 0 && (
              <div className="questions-block" data-testid="questions-block">
                {questions.map((q, i) => (
                  <fieldset key={`${q.field}-${i}`} className="question-item" data-testid="question-item">
                    <legend>{q.text}</legend>
                    <div className="question-actions">
                      {q.suggested_answers.map((s) => (
                        <button key={s} type="button" className="secondary suggestion-btn" aria-pressed={!skipped[i] && answers[i] === s} onClick={() => pick(i, s, false)}>{s}</button>
                      ))}
                      <button type="button" className="secondary skip-btn" data-testid={`skip-question-${i}`} aria-pressed={Boolean(skipped[i])} onClick={() => pick(i, null, true)}>Skip</button>
                    </div>
                    <input type="text" className="question-input" aria-label={`Answer for ${q.text}`} value={skipped[i] ? "" : (answers[i] ?? "")} onChange={(e) => pick(i, e.target.value, false)} />
                    {skipped[i] && q.suggested_answers[0] && <p className="assumed-note" data-testid="assumed-note">{`Assumed: ${q.suggested_answers[0]}`}</p>}
                  </fieldset>
                ))}
              </div>
            )}
          </>
        )}
      </Loaded>
      <Primary label="Continue" action={action} disabled={!intake || bad.size > 0} />
    </div>
  );
}
