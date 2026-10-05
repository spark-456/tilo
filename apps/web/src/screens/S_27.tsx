// S-27 My plate (PRD addendum FR-PA-02, FR-PA-03; ADR-0016): the signed-in person's open work
// items in one deterministic order, each with Done, Snooze and Not mine. Fixture data only
// (src/people/data.ts) and a notice that says so; no design export covers it, so cards and rows
// follow kit.tsx in neutral role tokens. Only the person's own items are read (PE-03): of anyone
// else, a display name. Cards, mail, pins and the calendar join the plate when their sources are
// connected; none is shown or counted here.
import type { WorkItem } from "@tilo/contracts";
import { useReducer, useRef, useState } from "react";
import { QUOTES, WORK_ITEMS, personName } from "../people/data";
import { Evidence, PreviewNote } from "../people/parts";
import { type Bucket, bucketOf, byDue, canReject, laneOf, reducePlate } from "../people/plate";
import { Chip, EmptyState, Page, Row, Section, longDate, plural } from "./kit";

/** The open groups, in plate order: bucket, section title, chip tone and chip word. */
const BUCKETS: ReadonlyArray<readonly [Bucket, string, string, string]> = [
  ["overdue", "Overdue", "blocked", "Overdue"],
  ["soon", "Due in the next 48 hours", "needs", "Due soon"],
  ["rest", "The rest", "fyi", "Later"],
];
const LANES = [
  ["snoozed", "Snoozed"],
  ["asked", "Asked to be reassigned"],
  ["done", "Done"],
] as const;

const sourceOf = (i: WorkItem): string =>
  i.source.kind === "meeting"
    ? `From a meeting${i.assigned_by && i.assigned_by.by !== i.owner ? `, assigned by ${personName(i.assigned_by.by)}` : ""}`
    : i.source.kind === "mail"
      ? "From mail you marked to track"
      : "Added by you";

const dueOf = (i: WorkItem): string =>
  i.due
    ? `Due ${longDate(`${i.due}T00:00:00Z`)}${i.due_text ? ` (${i.due_text})` : ""}`
    : "No due date";

export function S_27() {
  const [items, act] = useReducer(reducePlate, WORK_ITEMS);
  const [said, setSaid] = useState("");
  const status = useRef<HTMLOutputElement>(null);
  const inLane = (lane: string) => items.filter((i) => laneOf(i) === lane).sort(byDue);
  const open = inLane("open");

  const row = (i: WorkItem, chip?: readonly [string, string]) => {
    const meeting = i.source.kind === "meeting" ? (i.source.ref ?? "").split("#")[0] : undefined;
    const button = (kind: "done" | "snooze" | "not_mine", says: string) => () => {
      act({ kind, id: i.id });
      setSaid(`${says}: ${i.title}.`);
      status.current?.focus(); // the row leaves the list, so focus moves to what happened
    };
    const actions: ReadonlyArray<
      readonly [string, string, string, "done" | "snooze" | "not_mine"]
    > = [
      ["Done", "Done", "Marked done", "done"],
      ["Snooze", "Snooze until tomorrow", "Snoozed until tomorrow", "snooze"],
      ...(canReject(i)
        ? ([["Not mine", "Not mine", "Asked for it to be reassigned", "not_mine"]] as const)
        : []),
    ];
    return (
      <Row
        key={i.id}
        name={i.title}
        sub={`${sourceOf(i)}. ${dueOf(i)}.`}
        state={
          <>
            {i.flagged && <Chip tone="needs">Flagged: any follow-up needs you</Chip>}
            {chip && <Chip tone={chip[0]}>{chip[1]}</Chip>}
          </>
        }
      >
        {laneOf(i) === "open" && (
          <div className="plate-actions">
            {actions.map(([text, name, says, kind]) => (
              <button
                key={kind}
                type="button"
                className="secondary"
                aria-label={`${name}: ${i.title}`}
                onClick={button(kind, says)}
              >
                {text}
              </button>
            ))}
          </div>
        )}
        {meeting && QUOTES[meeting] && <Evidence meeting={meeting} ids={i.source.evidence} />}
      </Row>
    );
  };

  return (
    <Page
      testid="plate"
      title="My plate"
      sub="What is waiting on you, in one fixed order: overdue first, then due in the next 48 hours, then the rest."
    >
      <PreviewNote what="Your plate" />
      <output ref={status} tabIndex={-1} className="plate-status" data-testid="plate-status">
        {said}
      </output>
      {open.length === 0 && (
        <EmptyState
          testid="plate-empty"
          title="Nothing is waiting on you"
          line="Open work items show up here when there are some."
        />
      )}
      {BUCKETS.map(([bucket, title, tone, word]) => {
        const rows = open.filter((i) => bucketOf(i.due) === bucket);
        return rows.length === 0 ? null : (
          <Section key={bucket} title={title} note={plural(rows.length, "item")}>
            <ul className="blist plate-list" data-testid={`plate-${bucket}`}>
              {rows.map((i) => row(i, [tone, word]))}
            </ul>
          </Section>
        );
      })}
      {LANES.map(([lane, title]) => {
        const rows = inLane(lane);
        return rows.length === 0 ? null : (
          <Section key={lane} title={title} note={plural(rows.length, "item")}>
            <ul className="blist plate-list" data-testid={`plate-${lane}`}>
              {rows.map((i) => row(i))}
            </ul>
          </Section>
        );
      })}
    </Page>
  );
}
