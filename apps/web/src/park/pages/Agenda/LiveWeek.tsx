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
import { CAL, CALENDAR_ENTRY_KIND, PX } from "./model";

const START_HOUR = 7;
const END_HOUR = 21;
const SLOTS_PER_DAY = (END_HOUR - START_HOUR) * 4;

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

export function LiveWeek({
  rows,
  parked,
  today: _today,
  meetings,
  onSchedule,
  host,
  hostState,
  minutes,
  getJson,
  onMeetHere,
  onDeleted,
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
}) {
  const [start, setStart] = useState(() => monday(new Date()));
  const [view, setView] = useState<"Day" | "Week" | "Month">("Week");
  const [selectedDay, setSelectedDay] = useState(() => localDate(new Date()));

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
    const dayIdx = Math.floor(low / SLOTS_PER_DAY);
    const date = days[dayIdx];
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

  const titleDate = view === "Day" ? civilDate(selectedDay) : start;
  const titleText =
    view === "Month"
      ? new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(titleDate)
      : view === "Day"
        ? new Intl.DateTimeFormat(undefined, {
            weekday: "short",
            day: "numeric",
            month: "short",
            year: "numeric",
          }).format(titleDate)
        : `Week of ${new Intl.DateTimeFormat(undefined, {
            day: "numeric",
            month: "short",
            year: "numeric",
          }).format(titleDate)}`;

  const activeDays = view === "Day" ? [civilDate(selectedDay)] : days;
  const cols =
    view === "Day" ? "50px minmax(0,1fr)" : `50px repeat(${activeDays.length},minmax(0,1fr))`;
  const hours: number[] = [];
  for (let t = START_HOUR; t <= END_HOUR; t++) hours.push(t);

  const now = new Date();
  const nowMinutes = now.getHours() * 60 + now.getMinutes() - START_HOUR * 60;

  return (
    <section aria-label="Week calendar" className="park-agenda-section">
      <div className="park-agenda-sechead">
        <div>
          <h2 className="park-agenda-h2">{titleText}</h2>
          <div className="park-agenda-secsub">
            Choose an open time or drag across 15-minute slots to schedule.
          </div>
        </div>
        <div className="park-agenda-filters">
          {/* biome-ignore lint/a11y/useSemanticElements: a labelled group of calendar controls */}
          <div className="park-agenda-nav" role="group" aria-label="Calendar navigation">
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
              aria-label="Next week"
              onClick={() => navigate(1)}
            >
              ›
            </button>
          </div>
          <div className="park-agenda-viewswitch" role="radiogroup" aria-label="Calendar view">
            {(["Day", "Week", "Month"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                // biome-ignore lint/a11y/useSemanticElements: radio button
                role="radio"
                aria-checked={view === mode}
                className={`park-agenda-viewbtn${view === mode ? " is-active" : ""}`}
                onClick={() => setView(mode)}
              >
                {mode}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="park-agenda-navbtn"
            onClick={() => {
              const n = new Date();
              n.setMinutes(Math.ceil(n.getMinutes() / 15) * 15, 0, 0);
              onSchedule(n.toISOString(), 15);
            }}
          >
            + New
          </button>
        </div>
      </div>

      <div
        className="park-agenda-weekgrid"
        data-week-grid=""
        style={{
          gridTemplateColumns: selected ? "minmax(0,1fr) 340px" : "minmax(0,1fr)",
        }}
      >
        <section className="park-agenda-cal" aria-label="Month calendar" hidden={view !== "Month"}>
          <div className="park-agenda-monthgrid">
            {monthDays.map((day) => {
              const key = localDate(day);
              const isToday = key === localDate(new Date());
              const dayEvents = entries.filter((entry) => localDate(new Date(entry.start)) === key);
              return (
                <div key={key} className={`park-agenda-monthcell${isToday ? " is-today" : ""}`}>
                  <div className="park-agenda-dayline">
                    <button
                      type="button"
                      className="park-agenda-monthday-btn"
                      aria-label={`Show ${key}`}
                      onClick={() => chooseDay(day)}
                    >
                      <span className="park-agenda-dayname">
                        {new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(day)}
                      </span>
                      <span className="park-agenda-daynum">{day.getDate()}</span>
                    </button>
                  </div>
                  <div className="park-agenda-monthevents">
                    {dayEvents.slice(0, 2).map((entry) => (
                      <button
                        key={entry.key}
                        type="button"
                        className="park-agenda-monthtag"
                        onClick={() => {
                          setSelected(entry);
                          setBriefRequested(false);
                        }}
                      >
                        {entry.title}
                      </button>
                    ))}
                    {dayEvents.length > 2 ? (
                      <span className="park-agenda-monthmore">+{dayEvents.length - 2} more</span>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="park-agenda-cal" aria-label="Week time slots" hidden={view === "Month"}>
          <div className="park-agenda-calhead" style={{ gridTemplateColumns: cols }}>
            <div />
            {activeDays.map((day) => {
              const dayKey = localDate(day);
              const isToday = dayKey === localDate(new Date());
              const dayEvents = entries.filter(
                (entry) => localDate(new Date(entry.start)) === dayKey,
              );
              const load = dayEvents.length
                ? `${dayEvents.length} event${dayEvents.length > 1 ? "s" : ""}`
                : "No events";
              const due = parked.filter((row) => row.due?.slice(0, 10) === dayKey && row.title);
              return (
                <div
                  key={dayKey}
                  className={`park-agenda-dayhead${isToday ? " is-today" : ""}${dayKey === selectedDay ? " is-selected" : ""}`}
                  style={{ background: isToday ? "var(--heroSoft)" : "transparent" }}
                >
                  <div className="park-agenda-dayline">
                    <span
                      className="park-agenda-dayname"
                      style={{ color: isToday ? "var(--heroInk)" : "var(--ink3)" }}
                    >
                      {new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(day)}
                    </span>
                    <span
                      className="park-agenda-daynum"
                      style={{
                        background: isToday ? "var(--heroFill)" : "transparent",
                        color: isToday ? "#FFFFFF" : "var(--ink)",
                      }}
                    >
                      {day.getDate()}
                    </span>
                  </div>
                  <div className="park-agenda-dayload">{load}</div>
                  {due.map((row) => (
                    <span className="park-agenda-due" key={`${row.ref.kind}:${row.ref.id}`}>
                      Due: {row.title}
                    </span>
                  ))}
                </div>
              );
            })}
          </div>
          <div
            className="park-agenda-calbody"
            style={{ gridTemplateColumns: cols, height: (END_HOUR - START_HOUR) * PX }}
          >
            <div className="park-agenda-hours">
              {hours.map((t) => (
                <div key={t} className="park-agenda-hour" style={{ top: (t - START_HOUR) * PX }}>
                  {`${String(t).padStart(2, "0")}:00`}
                </div>
              ))}
            </div>
            {activeDays.map((day, dayIndex) => {
              const dayKey = localDate(day);
              const isToday = dayKey === localDate(new Date());
              const isWeekend = day.getDay() === 0 || day.getDay() === 6;
              const dayEvents = entries.filter(
                (entry) => localDate(new Date(entry.start)) === dayKey,
              );
              const baseDayIdx =
                view === "Day"
                  ? Math.max(
                      0,
                      days.findIndex((d) => localDate(d) === dayKey),
                    )
                  : dayIndex;
              return (
                <div
                  key={dayKey}
                  className={`park-agenda-col${isToday ? " is-today" : ""}${dayKey === selectedDay ? " is-selected" : ""}`}
                  style={{
                    backgroundColor: isToday
                      ? "var(--rowOn)"
                      : isWeekend
                        ? "var(--sunk)"
                        : "transparent",
                  }}
                >
                  {Array.from({ length: SLOTS_PER_DAY }, (_, slot) => {
                    const index = baseDayIdx * SLOTS_PER_DAY + slot;
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
                        style={{ top: slot * 13, height: 13 }}
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
                  {dayEvents.map((entry, idx) => {
                    const date = new Date(entry.start);
                    const startH = date.getHours() + date.getMinutes() / 60;
                    if (startH < START_HOUR || startH >= END_HOUR) return null;
                    const offset = (startH - START_HOUR) * PX;
                    const end = entry.end ? new Date(entry.end) : null;
                    const durationH =
                      end && end > date ? (end.getTime() - date.getTime()) / 3_600_000 : 0.5;
                    const height = Math.max(22, Math.min(3, durationH) * PX - 3);

                    const calKey = entry.meeting ? "tilo" : idx % 2 === 0 ? "work" : "personal";
                    const [, bar, bg, fg] = CAL[calKey];
                    const on = selected?.key === entry.key;

                    const startFmt = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
                    const endFmt = end
                      ? `${String(end.getHours()).padStart(2, "0")}:${String(end.getMinutes()).padStart(2, "0")}`
                      : "";
                    const timeStr = endFmt ? `${startFmt}–${endFmt}` : startFmt;

                    const style: CSSProperties = {
                      top: offset + 1,
                      height,
                      borderLeftColor: bar,
                      background: bg,
                      color: fg,
                      boxShadow: on ? `0 0 0 2px ${bar}` : "none",
                      padding: height >= 35 ? "5px 7px" : "2px 7px",
                      zIndex: 2,
                    };

                    return (
                      <button
                        key={entry.key}
                        type="button"
                        className={`park-agenda-event${entry.meeting ? "" : " is-calendar-entry"}`}
                        data-event={entry.key}
                        aria-label={`${entry.title}, ${human(entry.start)}`}
                        style={style}
                        onClick={() => {
                          setSelected(entry);
                          setBriefRequested(false);
                        }}
                      >
                        <span className="park-agenda-eventline">
                          <span className="park-agenda-eventtitle">{entry.title}</span>
                          {entry.meeting ? (
                            <span role="img" aria-label="Tilo joins" className="park-agenda-badge">
                              {face({ rank: "director", expr: "neutral" }, 15, false)}
                            </span>
                          ) : null}
                        </span>
                        <span className="park-agenda-eventtime">{timeStr}</span>
                      </button>
                    );
                  })}
                  {slotPick?.day === baseDayIdx ? (
                    <fieldset
                      className="park-agenda-slot-popover"
                      style={{
                        top: Math.min(slotPick.slot * 13 + 14, (END_HOUR - START_HOUR) * PX - 160),
                      }}
                      aria-label="Schedule at this time"
                    >
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
                  {isToday && nowMinutes >= 0 && nowMinutes <= (END_HOUR - START_HOUR) * 60 ? (
                    <div
                      className="park-agenda-now"
                      role="img"
                      aria-label="Current time"
                      style={{ top: (nowMinutes / 60) * PX }}
                    >
                      <span className="park-agenda-nowdot" />
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>

        {selected ? (
          <aside className="park-agenda-detail" aria-label="Event details">
            <div className="park-agenda-detailhead">
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                }}
              >
                <h3 className="park-agenda-detailtitle">{selected.title}</h3>
                <button
                  type="button"
                  className="park-agenda-detailclose"
                  aria-label="Close event details"
                  onClick={() => setSelected(null)}
                >
                  ×
                </button>
              </div>
              <div className="park-agenda-detailwhen">{selectedDate}</div>
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
            {selectedMeeting && getJson ? (
              <button
                type="button"
                className="park-btn park-btn--secondary"
                onClick={() => setBriefRequested(true)}
              >
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
              <button
                type="button"
                className="park-btn park-btn--primary"
                onClick={() => void join(selectedMeeting)}
              >
                Join now
              </button>
            ) : null}
            {joinError ? <p role="alert">{joinError}</p> : null}
            {selectedMeeting && minutes && ["ended", "minuted"].includes(selectedMeeting.status) ? (
              <MeetingMinutes
                id={selectedMeeting.id}
                status={selectedMeeting.status}
                api={minutes}
              />
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
          </aside>
        ) : null}
      </div>
    </section>
  );
}
