// S-27 My plate (PRD addendum FR-PA-02, FR-PA-03; ADR-0016): the signed-in person's open work
// items in one deterministic order, each with Done, Snooze and Not mine, and a strip of jump pills
// with the real counts. Fixture data only (src/people/data.ts) and a notice that says so; no design
// export covers it, so it follows the pills of "Tilo Worlds" and the people rows of "Tilo Team" in
// neutral role tokens. Only the person's own items are read (PE-03): of anyone else, a display
// name. Cards, mail, pins and the calendar join the plate when their sources are connected; none
// is shown or counted here.
import type { WorkItem } from "@tilo/contracts";
import { useEffect, useReducer, useRef, useState } from "react";
import { QUOTES, WORK_ITEMS, displayName } from "../people/data";
import { Evidence, PersonTag, PreviewNote, SourceIcon, pillLabel } from "../people/parts";
import {
  type Bucket,
  type PlateAction,
  bucketOf,
  byDue,
  canReject,
  laneOf,
  reducePlate,
} from "../people/plate";
import { Chip, EmptyState, Page, Section, longDate, plural } from "./kit";

type Key = Bucket | "snoozed" | "asked" | "done";
/** The groups in plate order: key, title, pill word. The first three are the open items. */
const GROUPS: ReadonlyArray<readonly [Key, string, string]> = [
  ["overdue", "Overdue", "Overdue"],
  ["soon", "Due in the next 48 hours", "Soon"],
  ["rest", "The rest", "Later"],
  ["snoozed", "Snoozed", "Snoozed"],
  ["asked", "Asked to be reassigned", "Reassigning"],
  ["done", "Done", "Done"],
];

/** "2026-10-09" or a timestamp -> "9 Oct". */
const short = (when: string): string =>
  longDate(when.length === 10 ? `${when}T00:00:00Z` : when).replace(/ \d{4}$/, "");

/** The state chip of an item in words, tinted by tone: the due date for an open item. */
function chipOf(i: WorkItem, key: Key): readonly [string, string] {
  if (key === "snoozed") return ["fyi", `Snoozed until ${short(i.snoozed_until ?? i.updated_at)}`];
  if (key === "asked")
    return ["fyi", `Waiting for ${displayName(i.assigned_by?.by ?? "")} to reassign`];
  if (key === "done") return ["done", `Done ${short(i.updated_at)}`];
  if (!i.due) return ["soon", "No due date"];
  return key === "overdue"
    ? ["blocked", `Overdue, ${short(i.due)}`]
    : key === "soon"
      ? ["needs", `Due soon, ${short(i.due)}`]
      : ["fyi", `Due ${short(i.due)}`];
}

function Source({ item: i }: { item: WorkItem }) {
  const by = i.assigned_by && i.assigned_by.by !== i.owner ? i.assigned_by.by : null;
  const said = i.due_text ? ` Said “${i.due_text}”.` : "";
  if (i.source.kind === "mail")
    return (
      <>
        <SourceIcon kind="mail" />
        From mail you marked to track.{said}
      </>
    );
  if (i.source.kind !== "meeting")
    return (
      <>
        <SourceIcon kind="you" />
        Added by you.{said}
      </>
    );
  return (
    <>
      <SourceIcon kind="meeting" />
      From a meeting{by && ", assigned by "}
      {by && <PersonTag user={by} />}.{said}
    </>
  );
}

export function S_27() {
  const [items, act] = useReducer(reducePlate, WORK_ITEMS);
  const [toast, setToast] = useState<{ text: string; undo: string | null } | null>(null);
  const undo = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLOutputElement>(null);
  // The row leaves its list, so focus moves to what happened: the toast's Undo, else the toast.
  useEffect(() => {
    if (toast) (undo.current ?? box.current)?.focus();
  }, [toast]);

  const keyOf = (i: WorkItem): Key => {
    const lane = laneOf(i);
    return lane === "open" ? bucketOf(i.due) : lane;
  };
  const rows = (key: Key) => items.filter((i) => keyOf(i) === key).sort(byDue);
  const groups = GROUPS.map(([key, title, word]) => ({ key, title, word, rows: rows(key) }));
  const empty = groups.slice(0, 3).every((g) => g.rows.length === 0);
  const jump = (key: Key) => {
    const el = document.getElementById(`plate-group-${key}`);
    el?.scrollIntoView({ block: "start" });
    el?.focus();
  };

  const run = (i: WorkItem, kind: PlateAction["kind"], says: string) => () => {
    act({ kind, id: i.id });
    setToast({ text: `${says}: ${i.title}.`, undo: kind === "put_back" ? null : i.id });
  };

  const item = (i: WorkItem, key: Key) => {
    const meeting = i.source.kind === "meeting" ? (i.source.ref ?? "").split("#")[0] : undefined;
    const [tone, word] = chipOf(i, key);
    const open = laneOf(i) === "open";
    const buttons: ReadonlyArray<readonly [string, string, string, PlateAction["kind"]]> = open
      ? [
          ["Done", "Done", "Marked done", "done"],
          ["Snooze", "Snooze until tomorrow", "Snoozed until tomorrow", "snooze"],
          ...(canReject(i)
            ? ([["Not mine", "Not mine", "Asked for it to be reassigned", "not_mine"]] as const)
            : []),
        ]
      : [["Put back", "Put back", "Put back", "put_back"]];
    return (
      <li key={i.id} className="prow" data-testid="plate-item">
        <div className="prow-title">
          <b>{i.title}</b>
          <span className="prow-chips">
            {i.flagged && <Chip tone="needs">Flagged: any follow-up needs you</Chip>}
            <Chip tone={tone}>{word}</Chip>
          </span>
        </div>
        <p className="bitem-sub">
          <Source item={i} />
        </p>
        {meeting && QUOTES[meeting] && <Evidence meeting={meeting} ids={i.source.evidence} />}
        <div className="plate-actions">
          {buttons.map(([text, name, says, kind]) => (
            <button
              key={kind}
              type="button"
              className="secondary"
              aria-label={`${name}: ${i.title}`}
              onClick={run(i, kind, says)}
            >
              {text}
            </button>
          ))}
        </div>
      </li>
    );
  };

  return (
    <Page
      testid="plate"
      title="My plate"
      sub="What is waiting on you, in one fixed order: overdue first, then due in the next 48 hours, then the rest."
    >
      <PreviewNote what="Your plate" />
      <nav className="people-strip" aria-label="Jump to a group" data-testid="plate-strip">
        {groups
          .filter((g) => g.rows.length > 0)
          .map((g) => (
            <button
              key={g.key}
              type="button"
              className="people-pill"
              data-testid={`pill-${g.key}`}
              onClick={() => jump(g.key)}
            >
              {pillLabel(g.word, g.rows.length)}
            </button>
          ))}
      </nav>
      {empty && (
        <div className="people-gap">
          <EmptyState
            testid="plate-empty"
            title="Nothing is waiting on you"
            line="Open work items show up here when there are some."
          />
        </div>
      )}
      {groups.map((g) =>
        g.rows.length === 0 ? null : (
          <div key={g.key} id={`plate-group-${g.key}`} tabIndex={-1} className="plate-group">
            <Section title={g.title} note={plural(g.rows.length, "item")}>
              <ul className="blist plate-list" data-testid={`plate-${g.key}`}>
                {g.rows.map((i) => item(i, g.key))}
              </ul>
            </Section>
          </div>
        ),
      )}
      {/* In the page's flow after the last group, in a box always as tall as a toast: it never
          covers a button, and appearing moves nothing. */}
      <output ref={box} tabIndex={-1} className="plate-toast-slot" data-testid="plate-toast">
        {toast && (
          <span className="plate-toast">
            <span data-testid="plate-status">{toast.text}</span>
            {toast.undo && (
              <button
                ref={undo}
                type="button"
                className="secondary"
                onClick={() => {
                  act({ kind: "put_back", id: toast.undo ?? "" });
                  setToast({ text: "Put back.", undo: null });
                }}
              >
                Undo
              </button>
            )}
          </span>
        )}
      </output>
    </Page>
  );
}
