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

/** How long the toast stays before it clears itself. */
const TOAST_MS = 8000;

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
  const slot = useRef<HTMLDivElement>(null);
  // One toast at a time: the next action replaces it. It leaves after TOAST_MS, unless focus is in
  // it (a keyboard user on Undo): then it waits and goes once focus has left.
  const [wait, setWait] = useState(0); // counts the times the clock found focus in the toast
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(
      () => (slot.current?.contains(document.activeElement) ? setWait(wait + 1) : setToast(null)),
      TOAST_MS,
    );
    return () => window.clearTimeout(timer);
  }, [toast, wait]);
  // Where focus goes once the acted row has left its list. It stays where the person is looking:
  // the next row's same control, else the group's own box (tabIndex -1). The toast is announced
  // by its live region, never focused, so acting never scrolls the page.
  const after = useRef<{ next: string | null; kind: string; group: Key } | null>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: runs once per change of the items
  useEffect(() => {
    const to = after.current;
    after.current = null;
    if (!to) return;
    const row = to.next ? document.querySelector(`[data-row="${to.next}"]`) : null;
    const control = row?.querySelector(`[data-kind="${to.kind}"]`) ?? row?.querySelector("button");
    const target =
      control ??
      document.getElementById(`plate-group-${to.group}`) ??
      document.querySelector(".plate-group");
    if (!(target instanceof HTMLElement)) return;
    target.focus({ preventScroll: true });
    // Scroll only when focus would otherwise be out of sight (Undo of a row far above).
    const r = target.getBoundingClientRect();
    if (r.bottom < 0 || r.top > window.innerHeight) target.scrollIntoView({ block: "nearest" });
  }, [items]);

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
    const group = keyOf(i);
    const list = rows(group);
    after.current = {
      next: list[list.findIndex((r) => r.id === i.id) + 1]?.id ?? null,
      kind,
      group,
    };
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
      <li key={i.id} className="prow" data-testid="plate-item" data-row={i.id}>
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
              data-kind={kind}
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
      {/* The last thing in the page, sticky to the bottom of the view so the result and Undo are
          on screen without scrolling. While a toast shows, it also takes its own height at the end
          of the page, so it never covers the last rows. The text is a polite live region that is
          always mounted, so the change is announced; focus stays on the list. */}
      <div
        ref={slot}
        className="plate-toast-slot"
        data-testid="plate-toast"
        data-on={toast !== null}
      >
        <div className="plate-toast" data-on={toast !== null}>
          <output data-testid="plate-status">{toast?.text}</output>
          {toast?.undo && (
            <button
              type="button"
              className="secondary"
              onClick={() => {
                const id = toast.undo ?? "";
                after.current = { next: id, kind: "done", group: "done" };
                act({ kind: "put_back", id });
                setToast({ text: "Put back.", undo: null });
              }}
            >
              Undo
            </button>
          )}
        </div>
      </div>
    </Page>
  );
}
