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
  onSchedule: (start: string, minutes: number, title?: string) => void;
  host: MeetingHostApi | null;
  hostState?: () => Promise<HostState>;
  minutes: MeetingMinutesApi | null;
  getJson: ((path: string) => Promise<unknown>) | null;
  onMeetHere?: (start: string, minutes: number, title?: string) => Promise<void>;
  onDeleted?: () => void;
  /** A phone shows one day at first: seven columns do not fit beside each other. */
  compact?: boolean;
}) {
  const [start, setStart] = useState(() => monday(new Date()));
  const [view, setView] = useState<"Day" | "Week" | "Month">(compact ? "Day" : "Week");
  const [selectedDay, setSelectedDay] = useState(() => localDate(new Date()));
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });
  const [cals, setCals] = useState<Record<Tone, boolean>>({
    work: true,
    personal: true,
    tilo: true,
  });
  const [quickTitle, setQuickTitle] = useState("");
  const [popAt, setPopAt] = useState<{ top: number; left: number } | null>(null);
  const allEntries: Entry[] = [
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
  const entries = allEntries.filter((entry) => cals[toneOf(entry)]);
  const todayKey = today?.slice(0, 10) ?? localDate(new Date());
  const todayEntries = entries
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
    const date = days[Math.floor(low / SLOTS_PER_DAY)];
    if (date)
      setSlotPick({
        day: Math.floor(low / SLOTS_PER_DAY),
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

  const openEntry = (entry: Entry, anchor: HTMLElement) => {
    const box = anchor.getBoundingClientRect();
    const width = document.documentElement.clientWidth || 1200;
    const height = document.documentElement.clientHeight || 800;
    const right = box.right + 8;
    const left = right + 320 > width ? box.left - 328 : right;
    setPopAt({ top: Math.max(8, Math.min(box.top, height - 360)), left: Math.max(8, left) });
    setSelected(entry);
    setBriefRequested(false);
  };
  const rangeDays = view === "Month" ? monthDays : days;
  const rangeKeys = new Set(rangeDays.map(localDate));
  const rangeEmpty = !entries.some((entry) => rangeKeys.has(localDate(new Date(entry.start))));
  const emptyLine = rangeEmpty ? (
    <p className="cx-agenda-emptyline">
      {view === "Month"
        ? "No events this month. Connect Google Calendar or press Create."
        : "No events this week. Connect Google Calendar or press Create."}
    </p>
  ) : null;
  const fullDate = (value: string): string => {
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? ""
      : new Intl.DateTimeFormat(undefined, {
          weekday: "long",
          day: "numeric",
          month: "long",
        }).format(date);
  };

  return (
    <section className="cx-agenda-liveweek" aria-label="Week calendar">
      <div className="cx-agenda-sidebar">
        <aside className="cx-agenda-minimonth" aria-label="Mini month">
          <strong>
            {new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(start)}
          </strong>
          <div className="cx-agenda-mini">
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => (
              <span aria-hidden="true" key={day}>
                {day.slice(0, 1)}
              </span>
            ))}
            {monthDays.map((day) => (
              <button
                key={localDate(day)}
                type="button"
                className={`${localDate(day) === todayKey ? "is-today" : ""} ${localDate(day) === selectedDay ? "is-selected" : ""} ${day.getMonth() === monthFirst.getMonth() ? "" : "is-outside"}`}
                aria-label={`Show ${new Intl.DateTimeFormat(undefined, { dateStyle: "full" }).format(day)}`}
                onClick={() => chooseDay(day)}
              >
                {day.getDate()}
              </button>
            ))}
          </div>
        </aside>
        <section className="cx-agenda-cals" aria-label="My calendars">
          <h2>My calendars</h2>
          {(["work", "personal", "tilo"] as const).map((tone) => (
            <label key={tone} className="cx-agenda-calrow" data-event-tone={tone}>
              <input
                type="checkbox"
                checked={cals[tone]}
                onChange={() => setCals((prev) => ({ ...prev, [tone]: !prev[tone] }))}
              />
              <span aria-hidden="true" className="cx-agenda-calbox" />
              {tone === "work" ? "Work" : tone === "personal" ? "Personal" : "Tilo"}
            </label>
          ))}
        </section>
        <section className="cx-agenda-today" aria-label="Today's calendar">
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
      <div className="cx-agenda-weektitle">
        <div>
          <h2>
            {new Intl.DateTimeFormat(
              undefined,
              view === "Day"
                ? { day: "numeric", month: "long", year: "numeric" }
                : { month: "long", year: "numeric" },
            ).format(view === "Day" ? civilDate(selectedDay) : view === "Week" ? days[3] : start)}
          </h2>
        </div>
        <div className="cx-agenda-weekactions">
          <button
            type="button"
            className="cx-agenda-create"
            onClick={() => {
              const now = new Date();
              now.setMinutes(Math.ceil(now.getMinutes() / 15) * 15, 0, 0);
              onSchedule(now.toISOString(), 15);
            }}
          >
            + Create
          </button>
          <button
            type="button"
            aria-label="Today"
            onClick={() => {
              setStart(monday(new Date()));
              setSelectedDay(localDate(new Date()));
            }}
          >
            Today
          </button>
          <button type="button" aria-label="Previous week" onClick={() => navigate(-1)}>
            ‹
          </button>
          <button type="button" aria-label="Next week" onClick={() => navigate(1)}>
            ›
          </button>
          <fieldset className="cx-agenda-views" aria-label="Calendar view">
            {(["Day", "Week", "Month"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                aria-pressed={view === mode}
                onClick={() => setView(mode)}
              >
                {mode}
              </button>
            ))}
          </fieldset>
        </div>
      </div>
      <section className="cx-agenda-month" aria-label="Month calendar" hidden={view !== "Month"}>
        {view === "Month" ? emptyLine : null}
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => (
          <span aria-hidden="true" className="cx-agenda-monthhead" key={day}>
            {day}
          </span>
        ))}
        {monthDays.map((day) => {
          const key = localDate(day);
          const dayEntries = entries
            .filter((entry) => localDate(new Date(entry.start)) === key)
            .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime());
          return (
            <div
              className={`cx-agenda-monthday${key === todayKey ? " is-today" : ""}${day.getMonth() === monthFirst.getMonth() ? "" : " is-outside"}`}
              key={key}
            >
              <button type="button" onClick={() => chooseDay(day)} aria-label={`Show ${key}`}>
                {day.getDate()}
              </button>
              {dayEntries.slice(0, MONTH_CHIPS).map((entry) => (
                <button
                  key={entry.key}
                  type="button"
                  className="cx-agenda-monthchip"
                  data-event-tone={toneOf(entry)}
                  onClick={(event) => openEntry(entry, event.currentTarget)}
                >
                  {entry.title}
                </button>
              ))}
              {dayEntries.length > MONTH_CHIPS ? (
                <button
                  type="button"
                  className="cx-agenda-monthmore"
                  onClick={() => chooseDay(day)}
                >
                  +{dayEntries.length - MONTH_CHIPS} more
                </button>
              ) : null}
            </div>
          );
        })}
      </section>
      <section
        className="cx-agenda-scroll"
        aria-label="Week time slots"
        data-view={view.toLowerCase()}
        hidden={view === "Month"}
      >
        {view === "Month" ? null : emptyLine}
        <div className="cx-agenda-headrow">
          <span aria-hidden="true" />
          {days.map((day) => {
            const dayKey = localDate(day);
            const due = parked.filter((row) => row.due?.slice(0, 10) === dayKey && row.title);
            const count = entries.filter(
              (entry) => localDate(new Date(entry.start)) === dayKey,
            ).length;
            return (
              <div
                key={dayKey}
                className={`${dayKey === localDate(new Date()) ? "is-today" : ""} ${dayKey === selectedDay ? "is-selected" : ""}`}
                {...(dayKey === localDate(new Date()) ? { "aria-current": "date" as const } : {})}
              >
                <span className="cx-agenda-dayline">
                  <span className="cx-agenda-dayname">{weekday(day)}</span>
                  <span className="cx-agenda-daynum">{day.getDate()}</span>
                </span>
                <span className="cx-agenda-dayload">
                  {dayKey === localDate(new Date()) ? "Today · " : ""}
                  {count === 0 ? "No events" : count === 1 ? "1 event" : `${count} events`}
                </span>
                {due.map((row) => (
                  <span className="cx-agenda-due" key={`${row.ref.kind}:${row.ref.id}`}>
                    Due: {row.title}
                  </span>
                ))}
              </div>
            );
          })}
        </div>
        <div className="cx-agenda-grid">
          <div className="cx-agenda-hours">
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
          {days.map((day, dayIndex) => {
            const dayKey = localDate(day);
            const events = entries.filter((entry) => localDate(new Date(entry.start)) === dayKey);
            const now = new Date();
            const nowMinutes = now.getHours() * 60 + now.getMinutes() - START_HOUR * 60;
            return (
              <div
                key={dayKey}
                className={`cx-agenda-day ${dayKey === localDate(new Date()) ? "is-today" : ""} ${dayKey === selectedDay ? "is-selected" : ""}`}
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
                {placeDay(events).map(({ entry, top, height, lane, lanes }) => (
                  <button
                    key={entry.key}
                    type="button"
                    className={`cx-agenda-event${entry.meeting ? "" : " is-calendar-entry"}`}
                    data-event-tone={toneOf(entry)}
                    style={{
                      top,
                      height,
                      left: `calc(${(lane / lanes) * 100}% + 3px)`,
                      width: `calc(${100 / lanes}% - 6px)`,
                    }}
                    onClick={(event) => openEntry(entry, event.currentTarget)}
                    aria-label={`${entry.title}, ${human(entry.start)}`}
                  >
                    <strong>{entry.title}</strong>
                    <span>{range(entry)}</span>
                  </button>
                ))}
                {slotPick?.day === dayIndex ? (
                  <fieldset
                    className={`cx-agenda-slot-popover${dayIndex >= 4 && view !== "Day" ? " is-right" : ""}`}
                    style={{ top: slotPick.slot * SLOT_HEIGHT + SLOT_HEIGHT }}
                    aria-label="Schedule at this time"
                  >
                    <input
                      type="text"
                      className="cx-agenda-addtitle"
                      aria-label="Add title"
                      placeholder="Add title"
                      value={quickTitle}
                      onChange={(event) => setQuickTitle(event.target.value)}
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
                            ...(quickTitle.trim() ? [quickTitle.trim()] : []),
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
                        Paste your Google Meet link in Meet with Tilo, and Tilo joins it as a guest.
                      </p>
                    )}
                    <button
                      type="button"
                      onClick={() => {
                        onSchedule(
                          slotStart(day, slotPick.slot).toISOString(),
                          slotPick.minutes,
                          ...(quickTitle.trim() ? [quickTitle.trim()] : []),
                        );
                        setSlotPick(null);
                        setQuickTitle("");
                      }}
                    >
                      Invite others...
                    </button>
                    <button type="button" className="secondary" onClick={() => setSlotPick(null)}>
                      Close
                    </button>
                    {actionError ? <p role="alert">{actionError}</p> : null}
                  </fieldset>
                ) : null}
                {dayKey === localDate(now) &&
                nowMinutes >= 0 &&
                nowMinutes < (END_HOUR - START_HOUR) * 60 ? (
                  <span
                    className="cx-agenda-nowline"
                    role="img"
                    aria-label="Current time"
                    style={{ top: (nowMinutes / 15) * SLOT_HEIGHT }}
                  />
                ) : null}
              </div>
            );
          })}
        </div>
      </section>
      {selected ? (
        <aside
          className="park-agenda-state cx-agenda-selected"
          aria-label="Event details"
          data-event-tone={toneOf(selected)}
          style={
            popAt
              ? ({
                  "--pop-top": `${popAt.top}px`,
                  "--pop-left": `${popAt.left}px`,
                } as CSSProperties)
              : undefined
          }
          onKeyDown={(event) => {
            if (event.key === "Escape") setSelected(null);
          }}
        >
          <button
            type="button"
            className="cx-agenda-close"
            aria-label="Close event details"
            onClick={() => setSelected(null)}
          >
            ×
          </button>
          <h3 className="cx-agenda-poptitle">
            <span aria-hidden="true" className="cx-agenda-popdot" />
            {selected.title}
          </h3>
          <p>{`${fullDate(selected.start)} · ${range(selected)}`}</p>
          {toneOf(selected) === "tilo" ? <p>Tilo joins and takes notes</p> : null}
          {selectedMeeting ? (
            attendeeNames === null ? (
              <p>Loading people…</p>
            ) : (
              <p>
                {attendeeNames.length ? attendeeNames.join(", ") : "No other people are listed."}
              </p>
            )
          ) : null}
          {selectedMeeting && getJson ? (
            <button type="button" onClick={() => setBriefRequested(true)}>
              Tilo brief me
            </button>
          ) : null}
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
          {selectedMeeting && host && selectedMeeting.status === "scheduled" ? (
            <button type="button" onClick={() => void join(selectedMeeting)}>
              Open meeting
            </button>
          ) : null}
          {joinError ? <p role="alert">{joinError}</p> : null}
          {selectedMeeting && minutes && ["ended", "minuted"].includes(selectedMeeting.status) ? (
            <MeetingMinutes id={selectedMeeting.id} status={selectedMeeting.status} api={minutes} />
          ) : null}
          {selectedMeeting && host && selectedMeeting.status === "scheduled" ? (
            <button
              type="button"
              className="secondary"
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
        </aside>
      ) : null}
    </section>
  );
}
