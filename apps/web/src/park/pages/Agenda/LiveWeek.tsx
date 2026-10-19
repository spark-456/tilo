import { type CSSProperties, type KeyboardEvent, useEffect, useRef, useState } from "react";
import type { HostState } from "../../../api/connect";
import type { MeetingHostApi } from "../../api/live/meetingHost";
import type { MeetingMinutesApi } from "../../api/live/meetingMinutes";
import type { PeopleRow } from "../../api/live/peopleLists";
import type { AgendaPlateRow } from "../../api/types";
import { AppLink } from "../../shared/AppLink";
import { openMeetTab } from "../../shared/hostMeetingRules";
import { MeetingBrief } from "./MeetingBrief";
import { MeetingAttend } from "./MeetingHost";
import { MeetingMinutes } from "./MeetingMinutes";
import { face } from "./icons";
import { CALENDAR_ENTRY_KIND } from "./model";

const START_HOUR = 7;
const END_HOUR = 21;
const SLOTS_PER_DAY = (END_HOUR - START_HOUR) * 4;
const SLOT_HEIGHT = 14;

const localDate = (date: Date): string =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

const civilDate = (value: string): Date => {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year ?? 0, (month ?? 1) - 1, day ?? 1);
};

const human = (value: string): string => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const time = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(
    date,
  );
  if (day === today) return `Today ${time}`;
  return `${new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short" }).format(date)} · ${time}`;
};

const monday = (value: Date): Date => {
  const date = new Date(value.getFullYear(), value.getMonth(), value.getDate());
  date.setDate(date.getDate() - ((date.getDay() + 6) % 7));
  return date;
};

const slotStart = (day: Date, slot: number): Date => {
  const start = new Date(day);
  start.setHours(START_HOUR, 0, 0, 0);
  start.setMinutes(start.getMinutes() + slot * 15);
  return start;
};

type Entry = { key: string; title: string; start: string; end: string | null; meeting?: PeopleRow };
type Tone = "work" | "tilo" | "personal";
// A calendar entry that carries no end is drawn as one 44 px block (the phone tap target); its end is not invented.
const MIN_EVENT_HEIGHT = 44;
const MONTH_CHIPS = 3;
const clock = (date: Date): string =>
  new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(date);
const weekday = (date: Date): string =>
  new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(date);
/** Google Calendar entries are Work, meetings Tilo hosts are Tilo, every other meeting is Personal. */
const toneOf = (entry: Entry): Tone =>
  !entry.meeting ? "work" : entry.meeting.source === "bot" ? "tilo" : "personal";
const range = (entry: Entry): string => {
  const start = new Date(entry.start);
  const end = entry.end ? new Date(entry.end) : null;
  return end && end > start ? `${clock(start)} – ${clock(end)}` : clock(start);
};
type Placed = { entry: Entry; top: number; height: number; lane: number; lanes: number };
/** Events of one day with their vertical box; overlapping events sit side by side in lanes. */
const placeDay = (events: Entry[]): Placed[] => {
  const boxes = events
    .flatMap((entry) => {
      const date = new Date(entry.start);
      const offset = (date.getHours() * 60 + date.getMinutes() - START_HOUR * 60) / 15;
      if (offset < 0 || offset >= SLOTS_PER_DAY) return [];
      const end = entry.end ? new Date(entry.end) : null;
      const minutes = end && end > date ? (end.getTime() - date.getTime()) / 60_000 : 0;
      const top = offset * SLOT_HEIGHT;
      const height = Math.min(
        Math.max(MIN_EVENT_HEIGHT, (minutes / 15) * SLOT_HEIGHT - 2),
        SLOTS_PER_DAY * SLOT_HEIGHT - top,
      );
      return [{ entry, top, height, bottom: top + height }];
    })
    .sort((a, b) => a.top - b.top || b.bottom - a.bottom);
  const placed: Placed[] = [];
  let cluster: { entry: Entry; top: number; height: number; lane: number }[] = [];
  let laneEnds: number[] = [];
  let clusterEnd = -1;
  const close = () => {
    for (const item of cluster) placed.push({ ...item, lanes: laneEnds.length });
    cluster = [];
    laneEnds = [];
  };
  for (const box of boxes) {
    if (cluster.length && box.top >= clusterEnd) close();
    let lane = laneEnds.findIndex((end) => end <= box.top);
    if (lane < 0) lane = laneEnds.length;
    laneEnds[lane] = box.bottom;
    cluster.push({ entry: box.entry, top: box.top, height: box.height, lane });
    clusterEnd = cluster.length === 1 ? box.bottom : Math.max(clusterEnd, box.bottom);
  }
  close();
  return placed;
};

export function LiveWeek({
  rows,
  parked,
  today,
  meetings,
  onSchedule,
  host,
  hostState,
  minutes,
  getJson,
  onMeetHere,
  onDeleted,
  compact = false,
}: {
  rows: AgendaPlateRow[];
  parked: AgendaPlateRow[];
  today?: string | null;
  meetings: PeopleRow[];
  onSchedule: (start: string, minutes: number) => void;
  host: MeetingHostApi | null;
  hostState?: () => Promise<HostState>;
  minutes: MeetingMinutesApi | null;
  getJson: ((path: string) => Promise<unknown>) | null;
  onMeetHere?: (start: string, minutes: number) => Promise<void>;
  onDeleted?: () => void;
  /** A phone shows one day at first: seven columns do not fit beside each other. */
  compact?: boolean;
}) {
  const [start, setStart] = useState(() => monday(new Date()));
  const [view, setView] = useState<"Day" | "Week" | "Month">(compact ? "Day" : "Week");
  const [selectedDay, setSelectedDay] = useState(() => localDate(new Date()));
  const [calFilters, setCalFilters] = useState<{ work: boolean; personal: boolean; tilo: boolean }>(
    {
      work: true,
      personal: true,
      tilo: true,
    },
  );
  const [quickTitle, setQuickTitle] = useState("");

  const days = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });

  const entries: Entry[] = [
    ...rows
      .filter((row) => row.ref.kind === CALENDAR_ENTRY_KIND && row.at && row.title)
      .map((row) => ({
        key: row.ref.id,
        title: row.title ?? "Calendar event",
        start: row.at as string,
        end: null,
      })),
    ...meetings
      .filter((meeting) => meeting.status !== "discarded")
      .map((meeting) => ({
        key: meeting.id,
        title: meeting.title,
        start: meeting.at,
        end: meeting.end,
        meeting,
      })),
  ];

  const todayKey = today?.slice(0, 10) ?? localDate(new Date());
  const visibleEntries = entries.filter((entry) => calFilters[toneOf(entry)]);
  const todayEntries = visibleEntries
    .filter((entry) => localDate(new Date(entry.start)) === todayKey)
    .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime());

  const [selected, setSelected] = useState<Entry | null>(null);
  const [briefRequested, setBriefRequested] = useState(false);
  const [attendeeNames, setAttendeeNames] = useState<string[] | null>(null);
  const drag = useRef<{ start: number; end: number } | null>(null);
  const suppressClick = useRef(false);
  const [joinError, setJoinError] = useState("");
  const [slotPick, setSlotPick] = useState<{ day: number; slot: number; minutes: number } | null>(
    null,
  );
  const [hostConnection, setHostConnection] = useState<HostState | null>(null);
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);

  const monthFirst = new Date(start.getFullYear(), start.getMonth(), 1);
  const monthGridStart = monday(monthFirst);
  const monthDays = Array.from({ length: 42 }, (_, index) => {
    const day = new Date(monthGridStart);
    day.setDate(monthGridStart.getDate() + index);
    return day;
  });

  const chooseDay = (day: Date) => {
    setSelectedDay(localDate(day));
    setStart(monday(day));
    setView("Day");
  };

  const navigate = (direction: number) => {
    const anchor = view === "Day" ? civilDate(selectedDay) : start;
    const next = new Date(anchor);
    if (view === "Month") next.setMonth(next.getMonth() + direction);
    else next.setDate(next.getDate() + direction * (view === "Week" ? 7 : 1));
    setSelectedDay(localDate(next));
    setStart(monday(next));
  };

  useEffect(() => {
    if (!slotPick) return;
    let live = true;
    setHostConnection("unknown");
    hostState?.().then(
      (state) => live && setHostConnection(state),
      () => live && setHostConnection("unknown"),
    );
    return () => {
      live = false;
    };
  }, [hostState, slotPick]);

  const labelDate = (date: Date) => {
    const isToday = localDate(date) === localDate(new Date());
    const day = new Intl.DateTimeFormat(undefined, {
      weekday: "short",
      day: "numeric",
      month: "short",
    }).format(date);
    return isToday ? `Today · ${day}` : day;
  };

  const schedule = (first: number, last: number) => {
    const low = Math.min(first, last);
    const span = Math.max(15, (Math.abs(last - first) + 1) * 15);
    const dayIdx = view === "Day" ? 0 : Math.floor(low / SLOTS_PER_DAY);
    const date = view === "Day" ? civilDate(selectedDay) : days[dayIdx];
    if (date)
      setSlotPick({
        day: dayIdx,
        slot: low % SLOTS_PER_DAY,
        minutes: span,
      });
  };

  const moveFocus = (button: HTMLButtonElement, delta: number) => {
    const all = Array.from(document.querySelectorAll<HTMLButtonElement>("[data-week-slot]"));
    const next = all.indexOf(button) + delta;
    all[next]?.focus();
  };

  const onSlotKey = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      schedule(index, index);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      moveFocus(event.currentTarget, SLOTS_PER_DAY);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      moveFocus(event.currentTarget, -SLOTS_PER_DAY);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      moveFocus(event.currentTarget, 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveFocus(event.currentTarget, -1);
    }
  };

  const selectedMeeting = selected?.meeting;
  const selectedMeetingId = selectedMeeting?.id;
  useEffect(() => {
    if (!selectedMeetingId || !getJson) {
      setAttendeeNames(null);
      return;
    }
    let live = true;
    setAttendeeNames(null);
    getJson(`/v1/meetings/${encodeURIComponent(selectedMeetingId)}`).then(
      (value) => {
        if (!live) return;
        const attendees =
          value &&
          typeof value === "object" &&
          "attendees" in value &&
          Array.isArray(value.attendees)
            ? value.attendees
            : [];
        setAttendeeNames(
          attendees.flatMap((attendee) =>
            attendee &&
            typeof attendee === "object" &&
            "name" in attendee &&
            typeof attendee.name === "string"
              ? [attendee.name]
              : [],
          ),
        );
      },
      () => live && setAttendeeNames([]),
    );
    return () => {
      live = false;
    };
  }, [getJson, selectedMeetingId]);

  const selectedDate = selected ? human(selected.start) : "";
  const join = async (meeting: PeopleRow) => {
    if (!host) return;
    const tab = openMeetTab();
    try {
      const call = await host.join(meeting.id);
      tab?.go(call.url);
    } catch {
      tab?.close();
      setJoinError("The Meet link is not available right now.");
    }
  };

  const activeDays = view === "Day" ? [civilDate(selectedDay)] : days;
  const now = new Date();
  const nowMinutes = now.getHours() * 60 + now.getMinutes() - START_HOUR * 60;

  const currentMonthYear = new Intl.DateTimeFormat(undefined, {
    month: "long",
    year: "numeric",
  }).format(view === "Day" ? civilDate(selectedDay) : start);

  return (
    <section className="park-agenda-liveweek cx-agenda-liveweek" aria-label="Week calendar">
      {/* 1. Top bar: "+ Create" button, "Today", < >, Month and Year as big title, Day | Week | Month switch */}
      <div className="park-agenda-topbar cx-agenda-weektitle">
        <div className="park-agenda-topbar-nav">
          <button
            type="button"
            className="park-agenda-create-btn"
            onClick={() => {
              const n = new Date();
              n.setMinutes(Math.ceil(n.getMinutes() / 15) * 15, 0, 0);
              onSchedule(n.toISOString(), 15);
            }}
            aria-label="Create event"
          >
            <span className="park-agenda-create-plus" aria-hidden="true">
              +
            </span>
            <span className="park-agenda-create-text">Create</span>
          </button>
          {/* biome-ignore lint/a11y/useSemanticElements: a labelled group of calendar controls */}
          <div className="park-agenda-nav" role="group" aria-label="Calendar navigation">
            <button
              type="button"
              className="park-agenda-todaybtn"
              aria-label="Today"
              onClick={() => {
                setStart(monday(new Date()));
                setSelectedDay(localDate(new Date()));
              }}
            >
              Today
            </button>
            <button
              type="button"
              className="park-agenda-navbtn"
              aria-label="Previous week"
              onClick={() => navigate(-1)}
            >
              ‹
            </button>
            <button
              type="button"
              className="park-agenda-navbtn"
              aria-label="Next week"
              onClick={() => navigate(1)}
            >
              ›
            </button>
          </div>
          <h2 className="park-agenda-month-title">{currentMonthYear}</h2>
        </div>
        <div className="park-agenda-weekactions cx-agenda-weekactions">
          <div
            className="park-agenda-viewswitch cx-agenda-views"
            role="radiogroup"
            aria-label="Calendar view"
          >
            {(["Day", "Week", "Month"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                // biome-ignore lint/a11y/useSemanticElements: view switch radio button
                role="radio"
                aria-checked={view === mode}
                aria-pressed={view === mode}
                className={`park-agenda-viewbtn${view === mode ? " is-active" : ""}`}
                onClick={() => setView(mode)}
              >
                {mode}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 2. Left column: mini-calendar (today circled), then "My calendars", then Today's calendar */}
      <div className="park-agenda-sidebar cx-agenda-sidebar">
        <details className="park-agenda-minidropdown" open>
          <summary className="park-agenda-minidropdown-summary">
            {new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(start)}
          </summary>
          <aside className="park-agenda-minimonth cx-agenda-minimonth" aria-label="Mini month">
            <strong>
              {new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(start)}
            </strong>
            <div className="park-agenda-mini cx-agenda-mini">
              {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
                <span aria-hidden="true" key={d}>
                  {d.slice(0, 1)}
                </span>
              ))}
              {monthDays.map((day) => (
                <button
                  key={localDate(day)}
                  type="button"
                  className={`${localDate(day) === todayKey ? "is-today" : ""} ${day.getMonth() === monthFirst.getMonth() ? "" : "is-outside"}`}
                  aria-label={`Show ${new Intl.DateTimeFormat(undefined, { dateStyle: "full" }).format(day)}`}
                  onClick={() => chooseDay(day)}
                >
                  {day.getDate()}
                </button>
              ))}
            </div>
          </aside>
        </details>

        <section className="park-agenda-mycals" aria-label="My calendars">
          <h3 className="park-agenda-mycals-title">My calendars</h3>
          <div className="park-agenda-mycals-list">
            {(["work", "personal", "tilo"] as const).map((tone) => (
              <label key={tone} className="park-agenda-calcheck">
                <input
                  type="checkbox"
                  checked={calFilters[tone]}
                  onChange={() => setCalFilters((prev) => ({ ...prev, [tone]: !prev[tone] }))}
                />
                <span className="park-agenda-calcheck-box" data-event-tone={tone} />
                <span className="park-agenda-calcheck-text">
                  {tone === "work" ? "Work" : tone === "personal" ? "Personal" : "Tilo"}
                </span>
              </label>
            ))}
          </div>
        </section>

        <section className="park-agenda-today cx-agenda-today" aria-label="Today's calendar">
          <h2>Today's calendar</h2>
          {todayEntries.length ? (
            <ul>
              {todayEntries.map((entry) => (
                <li key={entry.key} data-event-tone={toneOf(entry)}>
                  <strong>{entry.title}</strong>
                  <time dateTime={entry.start}>{human(entry.start)}</time>
                </li>
              ))}
            </ul>
          ) : (
            <p>No events today.</p>
          )}
          <AppLink to="/connectors">Check Google Calendar</AppLink>
        </section>
      </div>

      {/* Main calendar area */}
      <div className="park-agenda-main">
        {/* 7. Empty state: when there are no events, the grid still looks like Google Calendar, plus one calm line */}
        {visibleEntries.length === 0 ? (
          <output className="park-agenda-calmline">
            No events this week. Connect Google Calendar or press Create.
          </output>
        ) : null}

        {/* 5. Month view: grid of days with up to 3 event chips and "+N more" */}
        <section
          className="park-agenda-month cx-agenda-month"
          aria-label="Month calendar"
          hidden={view !== "Month"}
        >
          {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
            <span aria-hidden="true" className="park-agenda-monthhead cx-agenda-monthhead" key={d}>
              {d}
            </span>
          ))}
          {monthDays.map((day) => {
            const key = localDate(day);
            const dayEntries = visibleEntries
              .filter((entry) => localDate(new Date(entry.start)) === key)
              .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime());
            return (
              <div
                className={`park-agenda-monthday cx-agenda-monthday${key === todayKey ? " is-today" : ""}${day.getMonth() === monthFirst.getMonth() ? "" : " is-outside"}`}
                key={key}
              >
                <button type="button" onClick={() => chooseDay(day)} aria-label={`Show ${key}`}>
                  {day.getDate()}
                </button>
                {dayEntries.slice(0, MONTH_CHIPS).map((entry) => (
                  <button
                    key={entry.key}
                    type="button"
                    className="park-agenda-monthchip cx-agenda-monthchip"
                    data-event-tone={toneOf(entry)}
                    onClick={() => {
                      setSelected(entry);
                      setBriefRequested(false);
                    }}
                  >
                    {entry.title}
                  </button>
                ))}
                {dayEntries.length > MONTH_CHIPS ? (
                  <button
                    type="button"
                    className="park-agenda-monthmore cx-agenda-monthmore"
                    onClick={() => chooseDay(day)}
                  >
                    +{dayEntries.length - MONTH_CHIPS} more
                  </button>
                ) : null}
              </div>
            );
          })}
        </section>

        {/* 3. Week view / 6. Day view */}
        <section
          className="park-agenda-scroll cx-agenda-scroll"
          aria-label="Week time slots"
          data-view={view.toLowerCase()}
          hidden={view === "Month"}
        >
          <div className="park-agenda-headrow cx-agenda-headrow">
            <span aria-hidden="true" />
            {activeDays.map((day) => {
              const dayKey = localDate(day);
              const due = parked.filter((row) => row.due?.slice(0, 10) === dayKey && row.title);
              const count = visibleEntries.filter(
                (entry) => localDate(new Date(entry.start)) === dayKey,
              ).length;
              const isToday = dayKey === localDate(new Date());
              return (
                <div
                  key={dayKey}
                  className={`park-agenda-dayhead ${isToday ? "is-today" : ""} ${dayKey === selectedDay ? "is-selected" : ""}`}
                  {...(isToday ? { "aria-current": "date" as const } : {})}
                >
                  <span className="park-agenda-dayline cx-agenda-dayline">
                    <span className="park-agenda-dayname cx-agenda-dayname">{weekday(day)}</span>
                    <span className="park-agenda-daynum cx-agenda-daynum">{day.getDate()}</span>
                  </span>
                  <span className="park-agenda-dayload cx-agenda-dayload">
                    {isToday ? "Today · " : ""}
                    {count === 0 ? "No events" : count === 1 ? "1 event" : `${count} events`}
                  </span>
                  {due.map((row) => (
                    <span
                      className="park-agenda-due cx-agenda-due"
                      key={`${row.ref.kind}:${row.ref.id}`}
                    >
                      Due: {row.title}
                    </span>
                  ))}
                </div>
              );
            })}
          </div>

          <div className="park-agenda-grid cx-agenda-grid">
            <div className="park-agenda-hours cx-agenda-hours">
              {Array.from({ length: END_HOUR - START_HOUR + 1 }, (_, hour) => {
                const label = `${String(START_HOUR + hour).padStart(2, "0")}:00`;
                return (
                  <div
                    key={label}
                    style={{ height: hour === END_HOUR - START_HOUR ? 24 : SLOT_HEIGHT * 4 }}
                  >
                    <span>{label}</span>
                  </div>
                );
              })}
            </div>

            {activeDays.map((day, dayIndex) => {
              const dayKey = localDate(day);
              const isToday = dayKey === localDate(new Date());
              const isWeekend = day.getDay() === 0 || day.getDay() === 6;
              const events = visibleEntries.filter(
                (entry) => localDate(new Date(entry.start)) === dayKey,
              );

              return (
                <div
                  key={dayKey}
                  className={`park-agenda-col park-agenda-day cx-agenda-day ${isToday ? "is-today" : ""} ${dayKey === selectedDay ? "is-selected" : ""} ${isWeekend ? "is-weekend" : ""}`}
                  style={{ height: SLOT_HEIGHT * SLOTS_PER_DAY }}
                >
                  {Array.from({ length: SLOTS_PER_DAY }, (_, slot) => {
                    const index = dayIndex * SLOTS_PER_DAY + slot;
                    const date = slotStart(day, slot);
                    const time = new Intl.DateTimeFormat(undefined, {
                      hour: "2-digit",
                      minute: "2-digit",
                    }).format(date);
                    return (
                      <button
                        key={date.toISOString()}
                        type="button"
                        data-week-slot={index}
                        aria-label={`${labelDate(day)}, ${time}, empty slot. Enter to schedule.`}
                        style={{ top: slot * SLOT_HEIGHT, height: SLOT_HEIGHT }}
                        onKeyDown={(event) => onSlotKey(event, index)}
                        onPointerDown={() => {
                          drag.current = { start: index, end: index };
                        }}
                        onPointerMove={() => {
                          if (drag.current) drag.current.end = index;
                        }}
                        onPointerEnter={() => {
                          if (drag.current) drag.current.end = index;
                        }}
                        onPointerUp={() => {
                          if (drag.current) {
                            const picked = drag.current;
                            drag.current = null;
                            suppressClick.current = true;
                            schedule(picked.start, Math.max(picked.end, index));
                          }
                        }}
                        onClick={() => {
                          if (suppressClick.current) {
                            suppressClick.current = false;
                            return;
                          }
                          schedule(index, index);
                        }}
                      />
                    );
                  })}

                  {/* Events */}
                  {placeDay(events).map(({ entry, top, height, lane, lanes }) => (
                    <button
                      key={entry.key}
                      type="button"
                      className={`park-agenda-event cx-agenda-event${entry.meeting ? "" : " is-calendar-entry"}`}
                      data-event-tone={toneOf(entry)}
                      style={{
                        top,
                        height,
                        left: `calc(${(lane / lanes) * 100}% + 3px)`,
                        width: `calc(${100 / lanes}% - 6px)`,
                      }}
                      onClick={() => {
                        setSelected(entry);
                        setBriefRequested(false);
                      }}
                      aria-label={`${entry.title}, ${human(entry.start)}`}
                    >
                      <strong>{entry.title}</strong>
                      <span>{range(entry)}</span>
                    </button>
                  ))}

                  {/* Quick create slot popover */}
                  {slotPick?.day === dayIndex ? (
                    <fieldset
                      className="park-agenda-slot-popover cx-agenda-slot-popover"
                      style={{
                        top: Math.min(
                          slotPick.slot * SLOT_HEIGHT + SLOT_HEIGHT,
                          SLOTS_PER_DAY * SLOT_HEIGHT - 170,
                        ),
                      }}
                      aria-label="Schedule at this time"
                    >
                      <input
                        type="text"
                        className="park-agenda-quick-input"
                        placeholder="Add title"
                        aria-label="Add title"
                        value={quickTitle}
                        onChange={(e) => setQuickTitle(e.target.value)}
                      />
                      <strong>{human(slotStart(day, slotPick.slot).toISOString())}</strong>
                      <p>Tilo will join at this time and prepare meeting notes.</p>
                      {hostConnection === "connected" ? (
                        <button
                          type="button"
                          disabled={busy || !onMeetHere}
                          onClick={() => {
                            setBusy(true);
                            setActionError("");
                            void onMeetHere?.(
                              slotStart(day, slotPick.slot).toISOString(),
                              slotPick.minutes,
                            )
                              .then(() => {
                                setSlotPick(null);
                                setQuickTitle("");
                                onDeleted?.();
                              })
                              .catch(() =>
                                setActionError(
                                  "Tilo could not start that meeting. Try again or invite others.",
                                ),
                              )
                              .finally(() => setBusy(false));
                          }}
                        >
                          {busy ? "Starting…" : "Meet with Tilo here"}
                        </button>
                      ) : (
                        <p>
                          Paste your Google Meet link in Meet with Tilo, and Tilo joins it as a
                          guest.
                        </p>
                      )}
                      <button
                        type="button"
                        onClick={() => {
                          onSchedule(slotStart(day, slotPick.slot).toISOString(), slotPick.minutes);
                          setSlotPick(null);
                          setQuickTitle("");
                        }}
                      >
                        Invite others...
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => {
                          setSlotPick(null);
                          setQuickTitle("");
                        }}
                      >
                        Close
                      </button>
                      {actionError ? <p role="alert">{actionError}</p> : null}
                    </fieldset>
                  ) : null}

                  {/* Red now-line with a dot, on today only */}
                  {isToday && nowMinutes >= 0 && nowMinutes < (END_HOUR - START_HOUR) * 60 ? (
                    <span
                      className="park-agenda-now park-agenda-nowline cx-agenda-nowline"
                      role="img"
                      aria-label="Current time"
                      style={{ top: (nowMinutes / 15) * SLOT_HEIGHT }}
                    >
                      <span className="park-agenda-nowdot" aria-hidden="true" />
                    </span>
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>
      </div>

      {/* 4. Google-style event popover card */}
      {selected ? (
        <aside
          className="park-agenda-state park-agenda-event-popover cx-agenda-selected"
          aria-label="Event details"
        >
          <button
            type="button"
            className="park-agenda-popover-close cx-agenda-close"
            aria-label="Close event details"
            onClick={() => setSelected(null)}
          >
            ×
          </button>
          <div className="park-agenda-popover-title-row">
            <span
              className="park-agenda-popover-dot"
              data-event-tone={toneOf(selected)}
              aria-hidden="true"
            />
            <h3>{selected.title}</h3>
          </div>
          <p className="park-agenda-popover-time">{selectedDate}</p>
          <div className="park-agenda-popover-tilo">
            <span role="img" aria-label="Tilo joins" className="park-agenda-badge">
              {face({ rank: "director", expr: "neutral" }, 15, false)}
            </span>
            <span>Tilo joins and takes notes</span>
          </div>
          {selectedMeeting ? (
            attendeeNames === null ? (
              <p>Loading people…</p>
            ) : (
              <p>
                {attendeeNames.length ? attendeeNames.join(", ") : "No other people are listed."}
              </p>
            )
          ) : null}
          <div className="park-agenda-popover-actions">
            <button
              type="button"
              className="park-btn park-btn--primary"
              onClick={() => {
                if (selectedMeeting) void join(selectedMeeting);
                else openMeetTab()?.go("https://meet.google.com");
              }}
            >
              Open meeting
            </button>
            {selectedMeeting && getJson && !briefRequested ? (
              <button
                type="button"
                className="park-btn park-btn--secondary"
                onClick={() => setBriefRequested(true)}
              >
                Tilo brief me
              </button>
            ) : null}
            {selectedMeeting && host && selectedMeeting.status === "scheduled" ? (
              <button
                type="button"
                className="park-btn park-btn--secondary"
                onClick={() =>
                  void host
                    .remove(selectedMeeting.id)
                    .then(() => {
                      setSelected(null);
                      onDeleted?.();
                    })
                    .catch(() => setJoinError("Could not delete this meeting."))
                }
              >
                Delete
              </button>
            ) : null}
          </div>
          {selectedMeeting && getJson && briefRequested ? (
            <MeetingBrief id={selectedMeeting.id} getJson={getJson} />
          ) : null}
          {selectedMeeting && selectedMeeting.source === "bot" && host ? (
            <MeetingAttend
              id={selectedMeeting.id}
              row={selectedMeeting}
              api={host}
              onChanged={() => undefined}
            />
          ) : null}
          {joinError ? <p role="alert">{joinError}</p> : null}
          {selectedMeeting && minutes && ["ended", "minuted"].includes(selectedMeeting.status) ? (
            <MeetingMinutes id={selectedMeeting.id} status={selectedMeeting.status} api={minutes} />
          ) : null}
        </aside>
      ) : null}
    </section>
  );
}
