import type { Brief, DeliverableFormat } from "@tilo/contracts";
import { useState } from "react";
import { useClient } from "../../api/ClientProvider";
import type { IntakeFileStatus, IntakeResult } from "../../api/client";
import { intakes, rememberIntake } from "../../api/intakes";
import { AppLink } from "../AppLink";
import { Loaded, Primary } from "../FlowShell";
import { type Remote, useAction } from "../remote";

// biome-ignore format: compact tuple table
const FIELDS = [["goal", "Goal"], ["deliverables", "Deliverables"], ["audience", "Audience"], ["deadline", "Deadline"], ["constraints", "Constraints"], ["sources", "Sources"], ["sensitivity", "Sensitivity"]] as const;
type BriefField = (typeof FIELDS)[number][0];

// biome-ignore format: compact enum sets from contracts/common.schema.json
const DATA_CLASSES = ["personal", "business", "public"] as const;
// biome-ignore format: compact enum sets from contracts/common.schema.json
const FORMATS = new Set<string>(["pdf", "pptx", "docx", "xlsx", "csv", "markdown", "google_slides", "google_docs", "google_sheets", "email", "in_app"]);

// S-01 hands its result over here: the client seam has no "get intake" call, so a brief exists only
// for a task submitted in this session (a direct link to any other task gets the empty notice).
// The map itself lives in src/api/intakes.ts, so the Park Api (FR-UX-13) can fill it without importing a screen.
export { rememberIntake };

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
  // brief.schema.json: constraints are 1-300 characters each, at most 20; sources at most 50, a label
  // 120 characters and a bare ref 2000.
  const cons = csv(d.constraints);
  if (cons.length > 20 || cons.some((c) => c.length > 300)) bad.add("constraints");
  const srcs = csv(d.sources);
  if (srcs.length > 50 || srcs.some((x, i) => x.length > (b.sources[i]?.label !== undefined ? 120 : 2000))) bad.add("sources");
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
  if (draft.constraints !== init.constraints && !bad.has("constraints")) edits.constraints = csv(draft.constraints);
  if (draft.sources !== init.sources && !bad.has("sources")) {
    edits.sources = csv(draft.sources).map((item, i) => {
      const orig = b.sources[i];
      if (!orig) return { kind: "web", ref: item };
      return orig.label !== undefined ? { ...orig, label: item } : { kind: orig.kind, ref: item };
    });
  }
  if (draft.sensitivity !== init.sensitivity && !bad.has("sensitivity")) edits.sensitivity = draft.sensitivity as Brief["sensitivity"];
  return edits;
}

const LIMITS: Partial<Record<BriefField, string>> = {
  goal: "Goal: 1 to 500 characters",
  audience: "Audience: 1 to 200 characters",
  deadline: "Deadline: a date as YYYY-MM-DD, or empty",
  deliverables:
    "Deliverables: up to 10, each 'Title (format)' with a title under 120 characters and a known format",
  constraints: "Constraints: up to 20, each under 300 characters",
  sources: "Sources: up to 50, each short enough to read as a label",
  sensitivity: "Sensitivity: personal, business or public",
};
/** Why Continue is off, in words (colour and the disabled state alone never say it). */
const continueReason = (has: boolean, bad: Set<BriefField>): string | null =>
  !has
    ? null
    : bad.size === 0
      ? null
      : `Continue is off until these are fixed. ${FIELDS.filter(([f]) => bad.has(f))
          .map(([f]) => LIMITS[f])
          .join(". ")}.`;

// biome-ignore format: compact status formatter
const fileStatus = (f: IntakeFileStatus): string =>
  f.safety_flagged ? `Flagged: ${f.reason ?? ""}`.trim() : f.status === "failed" ? `Couldn't read: ${f.reason ?? ""}`.trim() : f.status;

// biome-ignore format: compact component
export function Understanding({ taskId }: { taskId: string }) {
  const client = useClient();
  const intake = intakes.get(taskId) ?? null;
  // Read in the first render, not through a loading state: the brief is already in memory, so a
  // "Loading" box here would only shift the layout when the form replaces it.
  const remote: Remote<IntakeResult | null> = { status: "ready", value: intake };
  const [draft, setDraft] = useState<Record<BriefField, string> | null>(() => (intake ? toDraft(intake.brief) : null));
  const activeDraft = draft ?? (intake ? toDraft(intake.brief) : null);
  const bad = intake && activeDraft ? invalidFields(intake.brief, activeDraft) : new Set<BriefField>();
  const questions = intake ? intake.questions.slice(0, 3) : [];
  const [answers, setAnswers] = useState<Record<number, string | null>>({});
  const [skipped, setSkipped] = useState<Record<number, boolean>>({});
  const pick = (i: number, val: string | null, isSkip: boolean) => { setSkipped((m) => ({ ...m, [i]: isSkip })); setAnswers((a) => ({ ...a, [i]: val })); };
  const choose = (i: number, label: string) => {
    const question = questions[i];
    if (!question || question.field !== "deliverables") { pick(i, label, false); return; }
    setSkipped(m => ({ ...m, [i]: false }));
    setAnswers(a => ({ ...a, [i]: toggleLabel(skipped[i] ? null : a[i], question.suggested_answers, label) }));
  };
  const reason = continueReason(Boolean(intake), bad);
  const action = useAction("confirm the brief", async () => {
    if (!intake || !activeDraft) throw new Error("no brief is loaded");
    const qAnswers = questions.map((q, i) => ({ field: q.field, answer: skipped[i] ? null : (answers[i] ?? null) }));
    await client.answerQuestions(taskId, qAnswers, toBriefEdits(intake.brief, activeDraft, bad));
    return `/task/${encodeURIComponent(taskId)}/approaches`;
  });

  // biome-ignore format: compact JSX
  return (
    <div className="s02-understanding">
      <Loaded what="the brief" remote={remote} isEmpty={(v) => v === null} empty={<><p>Tilo has no brief for this task in this session, so nothing is shown and nothing was changed.</p><AppLink to="/" className="secondary">Describe the task again</AppLink></>}>
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
                    {q.field === "deliverables" && <p className="section-note">Select all outputs you want.</p>}
                    <div className="question-actions">
                      {q.suggested_answers.map((s) => (
                        <button key={s} type="button" className="secondary suggestion-btn" aria-pressed={!skipped[i] && (q.field === "deliverables" ? pickedLabels(answers[i], q.suggested_answers).includes(s) : answers[i] === s)} onClick={() => choose(i, s)}>{s}</button>
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
      {reason && <output className="flow-detail" data-testid="continue-reason">{reason}</output>}
      <Primary label="Continue" action={action} disabled={!intake || bad.size > 0} />
    </div>
  );
}
import { pickedLabels, toggleLabel } from "../../api/intakeChoices";
