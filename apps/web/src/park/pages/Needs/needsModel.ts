// STUDIO-4 Needs you ("made clearer", design/studio-v2 "Tilo S Needs"): one decision at a time, each read as a plain
// question, what happens if yes, what happens if no, the cost and exactly what will be sent. Every line is derived from
// what the Api served for the decision (a live card's own fields, or the fixture's designed copy); nothing is invented.
// Pure: no clock, no fetch.
import type { Dec, Decision } from "../../api/types";

export type NeedKind = "gate" | "consent" | "question" | "provide" | "plain";

export interface NeedView {
  kind: NeedKind;
  /** The tag above the question ("Sends something", "Question", ...). */
  tag: string;
  question: string;
  /** The context under the question (the card's why, or the fixture body). */
  context: string;
  yes: string[];
  no: string[];
  /** The cost in words, or null when the Api reports none for this decision. */
  cost: string | null;
  /** Exactly what a yes releases, when the decision sends or shares something. */
  sent: { exact: string; to: string[]; item: string | null } | null;
  /** Why the person sees it, in plain words; null when nothing served says so. */
  why: string | null;
  /** Plain risk derived only from the served gate tier, reversibility and recipients. */
  risk: { tone: "low" | "medium" | "high" | "unknown"; label: string; detail: string } | null;
  /** Answer-by moment (ISO), or null when none was served. */
  due: string | null;
  /** The label of the answer a tap sends (a gate's fixed "Approve", the fixture's designed copy). */
  yesLabel: string;
  /** What that tap does, said beside the button. */
  yesSays: string;
}

const money = (pounds: number): string =>
  `£${pounds.toLocaleString("en-GB", { maximumFractionDigits: 2 })}`;

/** The moment the safe default applies: created_at plus timeout seconds; null when either is unreadable. */
export function dueOf(createdAt: string, timeout: number): string | null {
  const at = Date.parse(createdAt);
  if (!Number.isFinite(at) || !Number.isFinite(timeout) || timeout <= 0) return null;
  return new Date(at + timeout * 1000).toISOString();
}

/** "Thu 16 Oct, 18:00" in the reader's own time zone. */
export function dueLabel(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function needView(d: Decision): NeedView {
  const c = d.card;
  if (c?.kind === "gate" && c.gate) {
    const g = c.gate;
    const approve = c.options.find((o) => o.id === "approve");
    const yes = [g.exact];
    if (g.recipients.length)
      yes.push(
        `It reaches ${plural(g.recipients.length, "person", "people")}: ${g.recipients.join(", ")}`,
      );
    yes.push(
      g.irreversible ? "This cannot be undone once it is done." : "This can be undone later.",
    );
    const due = dueOf(c.createdAt, c.timeout);
    return {
      kind: "gate",
      tag: g.irreversible
        ? "Sends or shares something · cannot be undone"
        : "Sends or shares something",
      question: d.title,
      context: c.why,
      yes,
      no: [
        "Nothing is sent or shared.",
        "It stays on hold until you decide.",
        due
          ? `If nobody answers by ${dueLabel(due)}, it stays on hold.`
          : "If nobody answers, it stays on hold.",
      ],
      cost: null,
      sent: { exact: g.exact, to: g.recipients, item: g.item },
      why: `This step is a gate in the plan (risk ${g.riskTier}): Tilo never does it without a person’s answer.`,
      risk: {
        tone:
          g.riskTier === "T3"
            ? "high"
            : g.riskTier === "T2"
              ? "medium"
              : g.riskTier === "T1"
                ? "low"
                : "unknown",
        label:
          g.riskTier === "T3"
            ? "High risk"
            : g.riskTier === "T2"
              ? "Medium risk"
              : g.riskTier === "T1"
                ? "Low risk"
                : "Risk tier unavailable",
        detail: `${g.irreversible ? "This action cannot be undone" : "This action can be undone"}${
          g.recipients.length ? ` and reaches ${g.recipients.join(", ")}` : ""
        }.`,
      },
      due,
      yesLabel: approve?.label ?? d.yes,
      yesSays: "Approve releases exactly what is shown above, and nothing else.",
    };
  }
  if (c?.kind === "consent" && c.consent) {
    const due = dueOf(c.createdAt, c.timeout);
    return {
      kind: "consent",
      tag: "Connects an account",
      question: d.title,
      context: c.why,
      yes: [
        `Tilo connects ${c.consent.connector}.`,
        ...c.consent.scopes.map((s) => `It can: ${s}`),
      ],
      no: ["Nothing is connected.", "That connection waits until you decide."],
      cost: null,
      sent: null,
      why: "Connecting an account always needs a person’s answer.",
      risk: null,
      due,
      yesLabel: c.options.find((o) => o.id === "connect")?.label ?? d.yes,
      yesSays: "Connect grants only the access listed above.",
    };
  }
  if (d.provide) {
    return {
      kind: "provide",
      tag: "Needs details",
      question: d.title,
      context: c?.why ?? d.body,
      yes: [
        "Tilo uses the details you add here.",
        "The item comes back to you for approval before anything is sent.",
      ],
      no: ["The work waits for these details."],
      cost: null,
      sent: null,
      why: null,
      risk: null,
      due: c ? dueOf(c.createdAt, c.timeout) : null,
      yesLabel: "",
      yesSays: "",
    };
  }
  if (d.questionOptions) {
    const due = c ? dueOf(c.createdAt, c.timeout) : null;
    const fallback = c?.options.find((o) => o.id === c.safeDefault)?.label;
    return {
      kind: "question",
      tag: "Question",
      question: d.title,
      context: c?.why ?? d.body,
      yes: (
        c?.options ??
        d.questionOptions.map((o) => ({ ...o, suggested: false, irreversible: false }))
      ).map(
        (o) =>
          `“${o.label}”${o.suggested ? " (suggested)" : ""}${"reason" in o && o.reason ? `: ${o.reason}` : ""}`,
      ),
      no: fallback
        ? [
            due
              ? `If nobody answers by ${dueLabel(due)}, Tilo picks “${fallback}”.`
              : `If nobody answers, Tilo picks “${fallback}”.`,
          ]
        : ["The work waits for your answer."],
      cost: null,
      sent: null,
      why: null,
      risk: null,
      due,
      yesLabel: "",
      yesSays: "",
    };
  }
  // The fixture's decisions carry the prototype's designed copy and the additive facts.
  const f = d.facts;
  const yes = [d.body];
  if (f?.spendNote) yes.push(f.spendNote.decided);
  else if (f?.activity) yes.push(`${f.activity}.`);
  return {
    kind: "plain",
    tag: f?.amount != null ? "Spends money" : "Approval",
    question: d.title,
    context: f ? `${f.project} · ${f.subject}` : "",
    yes,
    no: ["Nothing is approved or sent.", "That part of the work stays paused until you decide."],
    cost: f?.amount != null ? money(f.amount) : null,
    sent: null,
    why: f?.approver ? `${f.approver} approves this kind of step.` : null,
    risk: null,
    due: null,
    yesLabel: d.yes,
    yesSays: f?.approveLabel ? `${f.approveLabel}: ${f.activity}.` : "",
  };
}

/** The decisions still open, in the order served; the ones taken on this page, in the same order. */
export function splitQueue(
  all: readonly Decision[],
  dec: Dec,
): { open: Decision[]; done: Decision[] } {
  return { open: all.filter((d) => !dec[d.k]), done: all.filter((d) => dec[d.k]) };
}

/** The one decision shown: the chosen one while it is open, else the first open one. */
export function currentOf(open: readonly Decision[], chosen: string | null): Decision | null {
  return open.find((d) => d.k === chosen) ?? open[0] ?? null;
}
