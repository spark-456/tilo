// S-29 Calendar (PRD addendum FR-CAL-01, -03, -05, -06; ADR-0016): the signed-in person's day or
// week in one merged agenda, each row citing its source record; Tilo's proposals marked as private
// until accepted; a teammate's time only as free/busy bars, never a title (PE-04); and a prep view
// for a meeting, assembled from records with no model (FR-CAL-05). Fixture data only
// (src/people/data.ts) and a notice that says so. Days are measured from the preview day (HR-1).
import type { CalendarEntryAgendaItem, Meeting } from "@tilo/contracts";
import { useEffect, useRef, useState } from "react";
import { addDays, agendaOf, barsOn, onDay, prepFor, weekOf, whenOf } from "../people/calendar";
import {
  AGENDA_ROWS,
  ALL_MEETINGS,
  CAL_ENTRIES,
  FREE_BUSY,
  MY_TIME_ZONE,
  PINS,
  PREVIEW_TODAY,
} from "../people/data";
import { PersonTag, PreviewNote, SoonButton } from "../people/parts";
import { AppLink } from "./AppLink";
import { Chip, EmptyState, Page, Section, longDate, plural } from "./kit";

const AGENDA = agendaOf(CAL_ENTRIES, AGENDA_ROWS);
const KIND_WORD = {
  event: "Event",
  due: "Due",
  reminder: "Reminder",
  meeting: "Meeting",
  deadline: "Pin deadline",
} as const;
const day = (d: string): string => longDate(`${d}T00:00:00Z`).replace(/ \d{4}$/, "");
const weekday = (d: string): string =>
  new Date(`${d}T00:00:00Z`).toLocaleDateString("en-GB", { weekday: "long", timeZone: "UTC" });

/** The record a row cites: a link where the record has a screen, else a label (FR-CAL-01). */
function Cite({ row }: { row: CalendarEntryAgendaItem }) {
  const { kind, id } = row.source;
  if (kind === "work_item") return <AppLink to="/plate">Source: a work item on your plate</AppLink>;
  if (kind === "pinboard_item") {
    const pin = PINS.find((p) => p.id === id);
    return <AppLink to="/pinboards">Source: {pin?.title ?? "a pin"}</AppLink>;
  }
  if (kind === "meeting")
    return <AppLink to={`/meetings/${id}`}>Source: the meeting record</AppLink>;
  const e = CAL_ENTRIES.find((c) => c.id === id);
  if (e?.source.kind === "google")
    return <>Source: Google Calendar, synced {longDate(e.source.synced_at)}</>;
  if (e?.source.kind === "tilo") return <>Source: Tilo, from a meeting action item</>;
  return <>Source: added by you</>;
}

function Availability({ dates }: { dates: readonly string[] }) {
  return (
    <Section
      title="Teammates' availability"
      note="Busy times only, 08:00 to 20:00. A teammate's titles are never shown."
    >
      <ul className="blist cal-free" data-testid="free-busy">
        {FREE_BUSY.flatMap((fb) =>
          dates.map((d) => {
            const bars = barsOn(fb, d);
            return (
              <li key={`${fb.user}${d}`} className="cal-free-row">
                <span className="cal-free-who">
                  <PersonTag user={fb.user} />
                  {dates.length > 1 && <span className="bitem-sub">{day(d)}</span>}
                </span>
                <span className="cal-bar" aria-hidden="true">
                  {bars.map((b) => (
                    <span
                      key={b.label}
                      className="cal-busy"
                      style={{ left: `${b.left}%`, width: `${b.width}%` }}
                    />
                  ))}
                </span>
                <span className="bitem-sub cal-free-text">
                  {bars.length === 0 ? "Free 08:00 to 20:00" : bars.map((b) => b.label).join(", ")}
                </span>
              </li>
            );
          }),
        )}
      </ul>
    </Section>
  );
}

function Prep({ meeting, onClose }: { meeting: Meeting; onClose: () => void }) {
  const head = useRef<HTMLHeadingElement>(null);
  useEffect(() => head.current?.focus(), []);
  const prep = prepFor(meeting);
  const none = (n: number, line: string) => n === 0 && <li className="evidence-none">{line}</li>;
  return (
    <Section
      title={`Prepare: ${meeting.title}`}
      headingRef={head}
      action={
        <button type="button" className="secondary" onClick={onClose}>
          Close prep
        </button>
      }
    >
      <div data-testid="prep">
        <h3 className="people-h3">Agenda</h3>
        <ul className="blist people-list">
          {meeting.agenda.map((a) => (
            <li key={a.title} className="prow">
              {a.title}
              {a.minutes !== null && <span className="bitem-sub"> ({a.minutes} min)</span>}
            </li>
          ))}
        </ul>
        <h3 className="people-h3">People involved</h3>
        <ul className="people-tags" aria-label="People involved">
          {meeting.attendees.map((a) => (
            <li key={a.name}>
              <PersonTag name={a.name} />
            </li>
          ))}
        </ul>
        <h3 className="people-h3">Related work items</h3>
        <ul className="blist people-list" data-testid="prep-items">
          {prep.workItems.map((i) => (
            <li key={i.id} className="prow">
              <AppLink to="/plate">{i.title}</AppLink>
            </li>
          ))}
          {none(prep.workItems.length, "No open work items from related meetings.")}
        </ul>
        <h3 className="people-h3">Related pins</h3>
        <ul className="blist people-list" data-testid="prep-pins">
          {prep.pins.map((p) => (
            <li key={p.id} className="prow">
              <AppLink to="/pinboards">{p.title}</AppLink>
            </li>
          ))}
          {none(prep.pins.length, "No pins from related meetings.")}
        </ul>
        <h3 className="people-h3">Previous minutes of this series</h3>
        <ul className="blist people-list" data-testid="prep-minutes">
          {prep.previous.map(({ meeting: m, minutes: x }) => (
            <li key={m.id} className="prow">
              <AppLink to={`/meetings/${m.id}`}>
                {m.title}, {longDate(m.scheduled?.start ?? m.created_at)}
              </AppLink>
              <span className="bitem-sub">{x.summary.map((s) => s.text).join(" ")}</span>
            </li>
          ))}
          {none(prep.previous.length, "No earlier minutes in this series.")}
        </ul>
      </div>
    </Section>
  );
}

export function S_29() {
  const [view, setView] = useState<"day" | "week">("day");
  const [date, setDate] = useState(PREVIEW_TODAY);
  const [prepId, setPrepId] = useState<string | null>(null);
  const dates = view === "day" ? [date] : weekOf(date);
  const step = view === "day" ? 1 : 7;
  const prepMeeting = ALL_MEETINGS.find((m) => m.id === prepId);

  const entry = (r: CalendarEntryAgendaItem) => {
    const proposed = r.state === "proposed";
    return (
      <li key={`${r.source.kind}${r.source.id}`} className="prow cal-row" data-testid="agenda-row">
        <div className="prow-title">
          <span className="cal-when">{whenOf(r)}</span>
          <b>{r.title}</b>
          <span className="prow-chips">
            <Chip tone={r.kind === "due" || r.kind === "deadline" ? "needs" : "fyi"}>
              {KIND_WORD[r.kind]}
            </Chip>
            {proposed && <Chip tone="soon">Proposed, private to you</Chip>}
            {r.shared && <Chip tone="fyi">Shared with your team</Chip>}
          </span>
        </div>
        <p className="bitem-sub">
          <Cite row={r} />
        </p>
        {proposed && (
          <div className="plate-actions">
            <SoonButton text="Accept" name={`Accept: ${r.title}`} />
            <SoonButton text="Decline" name={`Decline: ${r.title}`} />
          </div>
        )}
        {r.source.kind === "meeting" && (
          <div className="plate-actions">
            <button type="button" className="secondary" onClick={() => setPrepId(r.source.id)}>
              Prepare for {r.title}
            </button>
          </div>
        )}
      </li>
    );
  };

  const total = dates.reduce((n, d) => n + onDay(AGENDA, d).length, 0);
  return (
    <Page
      testid="calendar"
      title="Calendar"
      sub={`Your day or week in one list. Times are in your time zone, ${MY_TIME_ZONE}. Only you see your titles.`}
    >
      <PreviewNote what="This calendar" />
      <div className="cal-bar-controls">
        <fieldset className="filter-chips status-tabs people-strip" data-testid="cal-view">
          <legend className="visually-hidden">Show</legend>
          {(["day", "week"] as const).map((v) => (
            <label key={v} className="filter-chip">
              <input
                type="radio"
                name="cal-view"
                value={v}
                checked={view === v}
                onChange={() => setView(v)}
              />
              <span>{v === "day" ? "Day" : "Week"}</span>
            </label>
          ))}
        </fieldset>
        <div className="cal-nav">
          <button type="button" className="secondary" onClick={() => setDate(addDays(date, -step))}>
            Earlier
          </button>
          <button type="button" className="secondary" onClick={() => setDate(PREVIEW_TODAY)}>
            Today
          </button>
          <button type="button" className="secondary" onClick={() => setDate(addDays(date, step))}>
            Later
          </button>
        </div>
      </div>
      <Section
        title={
          view === "day" ? `${weekday(date)} ${day(date)}` : `Week of ${day(dates[0] ?? date)}`
        }
        note={plural(total, "item")}
      >
        {total === 0 && view === "day" ? (
          <EmptyState
            testid="cal-empty"
            compact
            title="Nothing on your calendar"
            line="Entries, due dates and meetings for this day show up here."
          />
        ) : (
          dates.map((d) => {
            const rows = onDay(AGENDA, d);
            return (
              <div key={d} className="cal-day" data-testid={`day-${d}`}>
                {view === "week" && (
                  <h3 className="people-h3">
                    {weekday(d)} {day(d)}
                    {d === PREVIEW_TODAY && " (today)"}
                  </h3>
                )}
                <ul className="blist plate-list">
                  {rows.map(entry)}
                  {rows.length === 0 && (
                    <li className="evidence-none cal-none">Nothing on this day.</li>
                  )}
                </ul>
              </div>
            );
          })
        )}
      </Section>
      {prepMeeting && <Prep meeting={prepMeeting} onClose={() => setPrepId(null)} />}
      <Availability dates={dates} />
    </Page>
  );
}
