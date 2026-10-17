import { type KeyboardEvent, useEffect, useRef, useState } from "react";
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

const START_HOUR = 8;
const END_HOUR = 20;
const SLOTS_PER_DAY = (END_HOUR - START_HOUR) * 4;
const SLOT_HEIGHT = 14;
const localDate = (date: Date): string =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
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
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });
  const entries: Entry[] = [
    ...rows
      .filter((row) => row.ref.kind === "calendar_entry" && row.at && row.title)
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

  return (
    <section className="cx-agenda-liveweek" aria-label="Week calendar">
      <div className="cx-agenda-weektitle">
        <div>
          <h2>
            Week of{" "}
            {new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" }).format(start)}
          </h2>
          <p>Choose an open time or drag across 15-minute slots to schedule.</p>
        </div>
        <div className="cx-agenda-weekactions">
          <button
            type="button"
            aria-label="Previous week"
            onClick={() =>
              setStart((day) => new Date(day.getFullYear(), day.getMonth(), day.getDate() - 7))
            }
          >
            ‹
          </button>
          <button type="button" aria-label="Today" onClick={() => setStart(monday(new Date()))}>
            Today
          </button>
          <button
            type="button"
            aria-label="Next week"
            onClick={() =>
              setStart((day) => new Date(day.getFullYear(), day.getMonth(), day.getDate() + 7))
            }
          >
            ›
          </button>
          <button
            type="button"
            onClick={() => {
              const now = new Date();
              now.setMinutes(Math.ceil(now.getMinutes() / 15) * 15, 0, 0);
              onSchedule(now.toISOString(), 15);
            }}
          >
            + New
          </button>
        </div>
      </div>
      <section className="cx-agenda-scroll" aria-label="Week time slots">
        <div className="cx-agenda-headrow">
          <span aria-hidden="true" />
          {days.map((day) => {
            const dayKey = localDate(day);
            const due = parked.filter((row) => row.due?.slice(0, 10) === dayKey && row.title);
            return (
              <div key={dayKey} className={dayKey === localDate(new Date()) ? "is-today" : ""}>
                {labelDate(day)}
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
            {Array.from({ length: END_HOUR - START_HOUR }, (_, hour) => {
              const label = `${String(START_HOUR + hour).padStart(2, "0")}:00`;
              return (
                <div key={label} style={{ height: SLOT_HEIGHT * 4 }}>
                  {label}
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
                className={`cx-agenda-day ${dayKey === localDate(new Date()) ? "is-today" : ""}`}
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
                {events.map((entry) => {
                  const date = new Date(entry.start);
                  const offset = (date.getHours() * 60 + date.getMinutes() - START_HOUR * 60) / 15;
                  if (offset < 0 || offset >= SLOTS_PER_DAY) return null;
                  const end = entry.end ? new Date(entry.end) : null;
                  const duration =
                    end && end > date
                      ? Math.min(180, (end.getTime() - date.getTime()) / 60_000)
                      : 15;
                  const height = Math.max(22, (duration / 15) * SLOT_HEIGHT);
                  return (
                    <button
                      key={entry.key}
                      type="button"
                      className={`cx-agenda-event${entry.meeting ? "" : " is-calendar-entry"}`}
                      style={{ top: offset * SLOT_HEIGHT, height }}
                      onClick={() => {
                        setSelected(entry);
                        setBriefRequested(false);
                      }}
                      aria-label={`${entry.title}, ${human(entry.start)}`}
                    >
                      <strong>{entry.title}</strong>
                      <span>{human(entry.start)}</span>
                    </button>
                  );
                })}
                {slotPick?.day === dayIndex ? (
                  <fieldset
                    className="cx-agenda-slot-popover"
                    style={{ top: slotPick.slot * SLOT_HEIGHT + SLOT_HEIGHT }}
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
                        {hostConnection === "unknown"
                          ? "Tilo could not confirm the meeting host. "
                          : "Tilo's meeting host is not signed in. "}
                        <AppLink to="/connectors">Sign in the meeting host</AppLink>
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
                {dayKey === localDate(now) &&
                nowMinutes >= 0 &&
                nowMinutes < (END_HOUR - START_HOUR) * 60 ? (
                  <span
                    className="cx-agenda-nowline"
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
        <aside className="park-agenda-state cx-agenda-selected" aria-label="Event details">
          <button
            type="button"
            className="cx-agenda-close"
            aria-label="Close event details"
            onClick={() => setSelected(null)}
          >
            ×
          </button>
          <h3>{selected.title}</h3>
          <p>{selectedDate}</p>
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
              Join now
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
