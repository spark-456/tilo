// S-07 gate sheet (PRD 18.3, 18.4, 10.4): the exact action, who receives it and whether it can be
// undone, then the three fixed options Approve, Edit first and Hold (card rule CR-07). Everything
// shown follows the gate's recorded events (HR-1): the gate counts as open only after an
// approval.resolved that says approve, or a policy.applied, arrives. A person-approved gate and a
// policy-opened one look different and both link to the authorisation (HR-7, BQ-49: a round
// "Policy" stamp with a check glyph in the policy colour). No design export shows the policy variant.
import type { Card, Event, Layout } from "@tilo/contracts";
import { AppLink } from "../screens/AppLink";
import { Chip, Soon, authzText, nameOf, stamp, words } from "../screens/kit";
import { type Answer, CardHead, CardOptions } from "./CardView";
import { DONE, type GateRecord, isOpen, policyLine, policyName } from "./gates";
import { RUNG, askedBy } from "./queue";

const OPTION = { approve: "Approve", edit: "Edit first", hold: "Hold" } as const;

const str = (e: Event, key: string): string => String((e.data as Record<string, unknown>)[key]);

interface Facts {
  readonly action: string;
  /** null: no recorded recipient (events never carry one; the card does). */
  readonly recipients: readonly string[] | null;
  readonly item: string | null;
  /** null: unknown (a policy event does not say). */
  readonly irreversible: boolean | null;
  readonly tier: string;
  readonly sent: boolean;
}

/** What the gate holds: from its card, else from the event that opened it. */
function factsOf(record: GateRecord, card: Card | null): Facts | null {
  if (card?.gate) {
    const g = card.gate;
    return {
      action: g.action.exact,
      recipients: g.recipients,
      item: g.action.item ? `${g.action.item.label}, version ${g.action.item.version}` : null,
      irreversible: g.irreversible,
      tier: g.risk_tier,
      sent: g.action.type === "send_email",
    };
  }
  const policy = record.outcome.state === "policy" ? record.outcome.event : null;
  const e = record.requested ?? policy;
  if (!e) return null;
  const version = (e.data as { item?: { version?: number } | null }).item?.version;
  return {
    action: words(str(e, "action_type")),
    recipients: null,
    item: e.item ? `${e.item.label}${version ? `, version ${version}` : ""}` : null,
    irreversible: policy ? null : (e.data as { irreversible?: boolean }).irreversible === true,
    tier: str(e, "risk_tier"),
    sent: str(e, "action_type") === "send_email",
  };
}

/** PRD 18.4 gate copy: exact action, recipient, irreversibility. */
function GateFacts({ f }: { f: Facts }) {
  const rows: ReadonlyArray<readonly [string, string] | null> = [
    ["The exact action", f.action],
    [
      "Who receives it",
      f.recipients === null
        ? "This replay did not record the recipient."
        : f.recipients.length === 0
          ? "No one: nothing leaves your own Drive."
          : f.recipients.join(", "),
    ],
    f.item ? ["What it holds", f.item] : null,
    f.irreversible === null
      ? null
      : [
          "Can it be undone?",
          !f.irreversible
            ? "Yes, you can undo it afterwards."
            : f.sent
              ? "Once sent, it can't be unsent."
              : "Once done, it can't be undone.",
        ],
    ["Risk tier", f.tier === "T3" ? "T3: a person always decides this." : f.tier],
  ];
  return (
    <dl className="gate-facts" data-testid="gate-facts">
      {rows.map((r) =>
        r ? (
          <div key={r[0]}>
            <dt>{r[0]}</dt>
            <dd>{r[1]}</dd>
          </div>
        ) : null,
      )}
    </dl>
  );
}

/** The round "Policy" stamp (BQ-49): a check glyph in the policy colour, and the word. */
function PolicyStamp() {
  return (
    <span className="policy-stamp" data-testid="policy-stamp">
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        <circle cx="8" cy="8" r="8" fill="var(--color-policy)" />
        <path
          d="M4.5 8.2l2.3 2.3 4.7-4.9"
          fill="none"
          stroke="#fff"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      Policy
    </span>
  );
}

/** What the recorded events say about the gate, in words: who opened or closed it and when. */
function Outcome({ record }: { record: GateRecord }) {
  const out = record.outcome;
  if (out.state === "policy") {
    const e = out.event;
    return (
      <div className="gate-status" data-testid="policy-line">
        <PolicyStamp />
        <p>
          {policyLine(
            DONE[str(e, "action_type")] ?? "Done",
            policyName(str(e, "policy_id")),
            Number(str(e, "undo_window_s")),
          )}
        </p>
      </div>
    );
  }
  if (out.state === "decided") {
    const who = out.event.authz ? authzText(out.event.authz) : "Someone";
    const when = out.event.authz ? ` at ${stamp(out.event.authz.at)}` : "";
    return (
      <p className="gate-status" data-testid="gate-outcome">
        {isOpen(record)
          ? `Opened. ${who} approved this${when}.`
          : `Kept closed. ${who} chose ${OPTION[out.option]}${when}.`}
      </p>
    );
  }
  return (
    <p className="gate-status" data-testid="gate-outcome">
      Waiting for your decision.
    </p>
  );
}

/** The gate sheet for one gate. `answer` is null where nothing can be sent (a view only). */
export function GateSheet({
  record,
  card,
  layout,
  answer,
}: { record: GateRecord; card: Card | null; layout: Layout | null; answer: Answer | null }) {
  const out = record.outcome;
  const policy = out.state === "policy" ? out.event : null;
  const lead = policy ?? record.requested;
  const facts = factsOf(record, card);
  return (
    <article
      className="gate-sheet"
      data-testid="gate-sheet"
      data-gate-state={out.state}
      data-opened-by={policy ? "policy" : isOpen(record) ? "person" : "none"}
    >
      {/* One reserved slot: the answer arriving moves nothing below it (UX-1, CLS). */}
      <div className="gate-slot">
        <Outcome record={record} />
      </div>
      {card ? (
        <CardHead card={card} layout={layout} />
      ) : (
        lead && (
          <>
            <div className="need-head">
              <Chip tone={policy ? "policy" : RUNG.gate.tone}>
                {policy ? "Opened by a rule" : RUNG.gate.label}
              </Chip>
              <span className="need-where">
                {policy ? policyName(str(policy, "policy_id")) : askedBy(layout, lead)}
              </span>
            </div>
            <h3 className="need-what">{lead.summary}</h3>
          </>
        )
      )}
      {facts && <GateFacts f={facts} />}
      {lead && (
        <AppLink to={`/world/${encodeURIComponent(lead.world_id)}/trace`} className="pill">
          See authorisation
        </AppLink>
      )}
      {/* The parts that change with the gate come last, so changing them moves nothing above. */}
      {out.state === "waiting" &&
        (card ? (
          <CardOptions card={card} answer={answer} />
        ) : (
          <>
            <p className="section-note">
              This replay did not record the card for this gate, so it cannot be answered here.
            </p>
            <Soon labels={Object.values(OPTION)} />
          </>
        ))}
      {policy && (
        <>
          <p className="section-note">
            {nameOf(str(policy, "connector"))} · {words(str(policy, "action_type"))}
          </p>
          <Soon labels={["Undo"]} />
        </>
      )}
    </article>
  );
}
