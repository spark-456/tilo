import type { Brief, DeliverableFormat } from "@tilo/contracts";
import { useState } from "react";
import { useClient } from "../../api/ClientProvider";
import type { IntakeFileStatus, IntakeResult } from "../../api/client";
import { BRIEF_SUPPLIER_COMPARISON } from "../../api/fixtures/brief";
import { FIXTURE_QUESTIONS } from "../../api/fixtures/derived";
import { Primary } from "../FlowShell";
import { useAction } from "../remote";

// biome-ignore format: compact tuple table
const FIELDS = [
  ["goal", "Goal"], ["deliverables", "Deliverables"], ["audience", "Audience"],
  ["deadline", "Deadline"], ["constraints", "Constraints"], ["sources", "Sources"],
  ["sensitivity", "Sensitivity"],
] as const;
type BriefField = (typeof FIELDS)[number][0];

const intakes = new Map<string, IntakeResult>();
export const rememberIntake = (i: IntakeResult): void => void intakes.set(i.task_id, i);

// biome-ignore format: compact helpers
const defaultIntake = (taskId: string): IntakeResult => ({
  task_id: taskId, brief: BRIEF_SUPPLIER_COMPARISON, questions: FIXTURE_QUESTIONS,
  files: [{ name: "quote_a.pdf", status: "ok", safety_flagged: false, reason: null }],
});

// biome-ignore format: compact helpers
const toDraft = (b: Brief): Record<BriefField, string> => ({
  goal: b.goal, audience: b.audience, deadline: b.deadline ?? "", sensitivity: b.sensitivity,
  deliverables: b.deliverables.map((d) => `${d.title} (${d.format})`).join(", "),
  constraints: b.constraints.join(", "), sources: b.sources.map((s) => s.label ?? s.ref).join(", "),
});

// biome-ignore format: compact brief edit parser
function toBriefEdits(b: Brief, draft: Record<BriefField, string>): Partial<Brief> {
  const init = toDraft(b);
  const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
  const edits: Partial<Brief> = {};
  if (draft.goal !== init.goal) edits.goal = draft.goal;
  if (draft.deliverables !== init.deliverables) {
    const fb = b.deliverables[0]?.format ?? "pdf";
    const items = csv(draft.deliverables).map((s) => {
      const m = /^(.+?)\s*\(([a-z_]+)\)$/i.exec(s);
      return m ? { title: m[1]?.trim() ?? s, format: m[2]?.toLowerCase() as DeliverableFormat } : { title: s, format: fb };
    });
    if (items[0]) edits.deliverables = [items[0], ...items.slice(1)];
  }
  if (draft.audience !== init.audience) edits.audience = draft.audience;
  if (draft.deadline !== init.deadline) edits.deadline = draft.deadline.trim() || null;
  if (draft.constraints !== init.constraints) edits.constraints = csv(draft.constraints);
  if (draft.sources !== init.sources) edits.sources = csv(draft.sources).map((ref) => ({ kind: "web", ref }));
  if (draft.sensitivity !== init.sensitivity) edits.sensitivity = draft.sensitivity.trim() as Brief["sensitivity"];
  return edits;
}

// biome-ignore format: compact status formatter
const fileStatus = (f: IntakeFileStatus): string =>
  f.safety_flagged ? `Flagged: ${f.reason ?? ""}`.trim() : f.status === "failed" ? `Couldn't read: ${f.reason ?? ""}`.trim() : f.status;

export function Understanding({ taskId }: { taskId: string }) {
  const client = useClient();
  const intake = intakes.get(taskId) ?? defaultIntake(taskId);
  const { brief } = intake;
  const questions = intake.questions.slice(0, 3);
  const [draft, setDraft] = useState<Record<BriefField, string>>(() => toDraft(brief));
  const [answers, setAnswers] = useState<Record<number, string | null>>({});
  const [skipped, setSkipped] = useState<Record<number, boolean>>({});
  const pick = (i: number, val: string | null, isSkip: boolean) => {
    setSkipped((m) => ({ ...m, [i]: isSkip }));
    setAnswers((a) => ({ ...a, [i]: val }));
  };
  const action = useAction("confirm the brief", async () => {
    const qAnswers = questions.map((q, i) => ({
      field: q.field,
      answer: skipped[i] ? null : (answers[i] ?? null),
    }));
    await client.answerQuestions(taskId, qAnswers, toBriefEdits(brief, draft));
    return `/task/${encodeURIComponent(taskId)}/approaches`;
  });

  // biome-ignore format: compact JSX
  return (
    <div className="s02-understanding">
      <div className="brief-chips" data-testid="brief-chips">
        {FIELDS.map(([f, label]) => (
          <label key={f} className="brief-chip" data-testid={`brief-chip-${f}`}>
            <span>{label}</span>
            <input type="text" value={draft[f]} onChange={(e) => setDraft((d) => ({ ...d, [f]: e.target.value }))} />
          </label>
        ))}
      </div>
      {intake.files.length > 0 && (
        <ul className="brief-list" data-testid="intake-files" aria-label="Files">
          {intake.files.map((f) => <li key={f.name} data-testid="intake-file">{`${f.name}: ${fileStatus(f)}`}</li>)}
        </ul>
      )}
      {brief.applied_preferences.length > 0 && (
        <ul className="brief-list" data-testid="applied-preferences" aria-label="Preferences">
          {brief.applied_preferences.map((p) => (
            <li key={`${p.field}-${p.citation.ref}`} data-testid="applied-preference">
              {`Using your preference: ${p.value} (${p.citation.ref}, ${p.citation.recorded_at})`}
            </li>
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
      <Primary label="Continue" action={action} />
    </div>
  );
}
