// The "This week" section (reference: the `This week` and `Event detail` regions of Tilo App Agenda.dc.html):
// calendar filters, week navigation, day/week/month view, drag-to-schedule with confirm sheet,
// 07-21 scroll, real now-line, and the detail aside.
import { type CSSProperties, useRef, useState } from "react";
import type { Agenda, AgendaSlot } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { Button, ModalScrim } from "../../components";
import { Detail } from "./Detail";
import { face, icon } from "./icons";
import {
  CAL,
  type CalKey,
  type Ev,
  PX,
  dayColumns,
  detailOf,
  eventsOf,
  findRuleOf,
  fmt,
  joinsOf,
  weekRange,
} from "./model";
import type { AgendaUi } from "./useAgenda";

const FILTERS: CalKey[] = ["work", "personal", "tilo"];
const START_HOUR = 7;
const END_HOUR = 21;

export interface DraggedItem {
  type: "pin" | "event";
  id: string;
  title: string;
}

function computeWeek(A: Agenda, offset: number): Agenda {
  if (offset === 0) return A;
  const match = A.days[0]?.match(/(\d+)/);
  const baseDay = match?.[1] ? Number.parseInt(match[1], 10) : 1;
  const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const days: string[] = [];
  const wkend: string[] = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date();
    d.setDate(baseDay + offset * 7 + i);
    const label = `${weekdays[i]} ${d.getDate()}`;
    if (i < 5) days.push(label);
    else wkend.push(label);
  }
  return {
    ...A,
    days,
    wkend,
    today: -1,
  };
}

function placeEvs(events: Ev[]): { event: Ev; lane: number; lanes: number }[] {
  const sorted = [...events].sort((a, b) => a.s - b.s || b.e - a.e);
  const placed: { event: Ev; lane: number; lanes: number }[] = [];
  let cluster: { event: Ev; lane: number }[] = [];
  let laneEnds: number[] = [];
  let clusterEnd = -1;

  const close = () => {
    const totalLanes = Math.max(1, laneEnds.length);
    for (const item of cluster) {
      placed.push({ event: item.event, lane: item.lane, lanes: totalLanes });
    }
    cluster = [];
    laneEnds = [];
  };

  for (const ev of sorted) {
    if (cluster.length && ev.s >= clusterEnd) {
      close();
    }
    let lane = laneEnds.findIndex((end) => end <= ev.s);
    if (lane < 0) {
      lane = laneEnds.length;
    }
    laneEnds[lane] = ev.e;
    cluster.push({ event: ev, lane });
    clusterEnd = cluster.length === 1 ? ev.e : Math.max(clusterEnd, ev.e);
  }
  close();
  return placed;
}

function MiniMonth({
  weekOffset: _weekOffset,
  onSelectOffset,
}: {
  weekOffset: number;
  onSelectOffset: (offset: number) => void;
}) {
  const now = new Date();
  const currentMonth = now.getMonth();
  const currentYear = now.getFullYear();
  const monthFirst = new Date(currentYear, currentMonth, 1);
  const startDay = new Date(monthFirst);
  const dayOfWeek = (startDay.getDay() + 6) % 7;
  startDay.setDate(startDay.getDate() - dayOfWeek);

  const cells: { date: Date; isToday: boolean; isCurrentMonth: boolean; offset: number }[] = [];
  const cellDate = new Date(startDay);
  for (let i = 0; i < 42; i++) {
    const isToday =
      cellDate.getDate() === now.getDate() &&
      cellDate.getMonth() === now.getMonth() &&
      cellDate.getFullYear() === now.getFullYear();
    const isCurrentMonth = cellDate.getMonth() === currentMonth;
    const nowMonday = new Date(now);
    nowMonday.setDate(now.getDate() - ((now.getDay() + 6) % 7));
    nowMonday.setHours(0, 0, 0, 0);
    const thisMonday = new Date(cellDate);
    thisMonday.setDate(cellDate.getDate() - ((cellDate.getDay() + 6) % 7));
    thisMonday.setHours(0, 0, 0, 0);
    const offset = Math.round((thisMonday.getTime() - nowMonday.getTime()) / (7 * 86400000));

    cells.push({
      date: new Date(cellDate),
      isToday,
      isCurrentMonth,
      offset,
    });
    cellDate.setDate(cellDate.getDate() + 1);
  }

  const monthLabel = new Intl.DateTimeFormat(undefined, {
    month: "long",
    year: "numeric",
  }).format(now);

  return (
    <aside className="park-agenda-minimonth" aria-label="Mini month">
      <strong>{monthLabel}</strong>
      <div className="park-agenda-mini">
        {["M", "T", "W", "T", "F", "S", "S"].map((d, idx) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: fixed day header list
          <span aria-hidden="true" key={idx}>
            {d}
          </span>
        ))}
        {cells.map((c) => (
          <button
            key={c.date.toISOString()}
            type="button"
            className={`${c.isToday ? "is-today" : ""} ${c.isCurrentMonth ? "" : "is-outside"}`}
            aria-label={`Show ${c.date.toDateString()}`}
            onClick={() => onSelectOffset(c.offset)}
          >
            {c.date.getDate()}
          </button>
        ))}
      </div>
    </aside>
  );
}

interface CalendarProps {
  A: Agenda;
  EV: Ev[];
  ui: AgendaUi;
  app: AppCtx;
  weekOffset: number;
  viewMode: "day" | "week" | "month";
  selectedDay: number;
  onConfirmSlot: (slot: AgendaSlot, item?: DraggedItem | undefined) => void;
}

function Calendar({
  A,
  EV,
  ui,
  app,
  weekOffset,
  viewMode,
  selectedDay,
  onConfirmSlot,
}: CalendarProps) {
  const allDays = dayColumns(A, EV, ui.cals, ui.weekend, ui.finding);
  const activeDayIndex = Math.max(
    0,
    Math.min(allDays.length - 1, selectedDay >= 0 ? selectedDay : 0),
  );
  const firstDay = allDays[0];
  const days = viewMode === "day" && firstDay ? [allDays[activeDayIndex] ?? firstDay] : allDays;
  const cols =
    viewMode === "day" ? "50px minmax(0,1fr)" : `50px repeat(${days.length},minmax(0,1fr))`;
  const hours: number[] = [];
  for (let t = START_HOUR; t <= END_HOUR; t++) hours.push(t);

  const dragSlot = useRef<AgendaSlot | null>(null);

  const now = new Date();
  const currentHour = now.getHours() + now.getMinutes() / 60;
  const nowPos =
    currentHour >= START_HOUR && currentHour <= END_HOUR
      ? (currentHour - START_HOUR) * PX
      : ((A.now ?? 9.2) - START_HOUR) * PX;

  const totalEvents = days.reduce((sum, d) => sum + d.events.length, 0);

  return (
    <div className="park-agenda-cal">
      {totalEvents === 0 ? (
        <p className="park-agenda-calmline">
          No events this week. Connect Google Calendar or press Create.
        </p>
      ) : null}
      <div className="park-agenda-calhead" style={{ gridTemplateColumns: cols }}>
        <div />
        {days.map((d) => (
          <div
            key={d.name}
            className="park-agenda-dayhead"
            style={{ background: d.today && weekOffset === 0 ? "var(--heroSoft)" : "transparent" }}
          >
            <div className="park-agenda-dayline">
              <span
                className="park-agenda-dayname"
                style={{
                  color: d.today && weekOffset === 0 ? "var(--heroInk)" : "var(--ink3)",
                }}
              >
                {d.name}
              </span>
              <span
                className={`park-agenda-daynum${d.today && weekOffset === 0 ? " is-today" : ""}`}
                style={{
                  background: d.today && weekOffset === 0 ? "var(--heroFill)" : "transparent",
                  color: d.today && weekOffset === 0 ? "#FFFFFF" : "var(--ink)",
                }}
              >
                {d.num}
              </span>
            </div>
            <div className="park-agenda-dayload">{d.load}</div>
          </div>
        ))}
      </div>
      <div
        className="park-agenda-calbody"
        style={{ gridTemplateColumns: cols, height: (END_HOUR - START_HOUR) * PX }}
      >
        <div className="park-agenda-hours">
          {hours.map((t) => (
            <div key={t} className="park-agenda-hour" style={{ top: (t - START_HOUR) * PX }}>
              {fmt(t)}
            </div>
          ))}
        </div>
        {days.map((d) => (
          <div
            key={d.name}
            className="park-agenda-col"
            style={{
              backgroundColor:
                d.today && weekOffset === 0
                  ? "var(--rowOn)"
                  : d.weekend
                    ? "var(--sunk)"
                    : "transparent",
            }}
          >
            {placeEvs(d.events).map(({ event: e, lane, lanes }) => {
              const [, bar, bg, fg] = CAL[e.cal];
              const on = ui.sel === e.id;
              const tall = e.e - e.s >= 0.75;
              const widthPct = 100 / lanes;
              const leftPct = lane * widthPct;
              const style: CSSProperties = {
                top: (e.s - START_HOUR) * PX + 1,
                height: Math.max(20, (e.e - e.s) * PX - 3),
                left: lanes > 1 ? `calc(${leftPct}% + 1px)` : "2px",
                width: lanes > 1 ? `calc(${widthPct}% - 3px)` : "calc(100% - 4px)",
                borderLeftColor: bar,
                background: bg,
                color: fg,
                boxShadow: on ? `0 0 0 2px ${bar}` : "none",
                padding: tall ? "5px 7px" : "2px 7px",
                opacity: e.past && !on ? 0.7 : 1,
              };
              return (
                <button
                  key={e.id}
                  type="button"
                  className="park-agenda-event"
                  data-event={e.id}
                  aria-pressed={on}
                  style={style}
                  onClick={() => ui.select(e.id)}
                  draggable={true}
                  onDragStart={(evt) => {
                    evt.dataTransfer.setData(
                      "application/json",
                      JSON.stringify({ type: "event", id: e.id, title: e.t }),
                    );
                    evt.dataTransfer.setData("text/plain", e.t);
                  }}
                >
                  <span className="park-agenda-eventline">
                    <span className="park-agenda-eventtitle" style={{ fontWeight: 600 }}>
                      {e.t}
                    </span>
                    {joinsOf(e, ui.flags) ? (
                      <span role="img" aria-label="Tilo joins" className="park-agenda-badge">
                        {face({ rank: "director", expr: "neutral" }, 15, app.night)}
                      </span>
                    ) : null}
                  </span>
                  {tall ? (
                    <span className="park-agenda-eventtime">{`${fmt(e.s)}–${fmt(e.e)}`}</span>
                  ) : null}
                </button>
              );
            })}
            {d.slots.map((s) => (
              <button
                key={s.l}
                type="button"
                className="park-agenda-slot"
                data-slot={s.l}
                aria-label={`Book ${s.l}, everyone is free`}
                style={{
                  top: (s.s - START_HOUR) * PX + 1,
                  height: Math.max(24, (s.e - s.s) * PX - 3),
                }}
                onPointerDown={() => {
                  dragSlot.current = s;
                }}
                onPointerUp={() => {
                  if (dragSlot.current && dragSlot.current.l !== s.l) {
                    const low = Math.min(dragSlot.current.s, s.s);
                    const high = Math.max(dragSlot.current.e, s.e);
                    dragSlot.current = null;
                    onConfirmSlot({
                      d: s.d,
                      s: low,
                      e: high,
                      l: `${d.name} ${fmt(low)}`,
                    });
                  } else {
                    dragSlot.current = null;
                  }
                }}
                onDragOver={(evt) => {
                  evt.preventDefault();
                  evt.dataTransfer.dropEffect = "move";
                }}
                onDrop={(evt) => {
                  evt.preventDefault();
                  let item: DraggedItem | undefined;
                  try {
                    const raw = evt.dataTransfer.getData("application/json");
                    if (raw) item = JSON.parse(raw);
                  } catch {}
                  if (!item) {
                    const title = evt.dataTransfer.getData("text/plain");
                    if (title) item = { type: "pin", title, id: "dragged" };
                  }
                  onConfirmSlot(s, item);
                }}
                onClick={() => void ui.book(s)}
              >
                {icon("plus", 13)}
                {`${fmt(s.s)} · all free`}
              </button>
            ))}
            {d.today && weekOffset === 0 ? (
              <div
                className="park-agenda-now"
                role="img"
                aria-label="Current time"
                style={{ top: nowPos }}
              >
                <span className="park-agenda-nowdot" />
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function MonthView({
  A,
  EV,
  ui,
  onSelectDay,
}: {
  A: Agenda;
  EV: Ev[];
  ui: AgendaUi;
  onSelectDay: (d: number) => void;
}) {
  const days = dayColumns(A, EV, ui.cals, true, false);
  return (
    <div className="park-agenda-cal">
      <div className="park-agenda-monthgrid">
        {days.map((d, index) => (
          <button
            key={d.name}
            type="button"
            className={`park-agenda-monthcell${d.today ? " is-today" : ""}`}
            onClick={() => onSelectDay(index)}
          >
            <div className="park-agenda-dayline">
              <span className="park-agenda-dayname">{d.name}</span>
              <span className="park-agenda-daynum">{d.num}</span>
            </div>
            <div className="park-agenda-dayload">{d.load}</div>
            <div className="park-agenda-monthevents">
              {d.events.slice(0, 3).map((e) => (
                <div key={e.id} className="park-agenda-monthtag">
                  {e.t}
                </div>
              ))}
              {d.events.length > 3 ? (
                <span className="park-agenda-monthmore">+{d.events.length - 3} more</span>
              ) : null}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

export function Week({ A, ui, app }: { A: Agenda; ui: AgendaUi; app: AppCtx }) {
  const [weekOffset, setWeekOffset] = useState(0);
  const [viewMode, setViewMode] = useState<"day" | "week" | "month">(
    app.vw <= 600 ? "day" : "week",
  );
  const [selectedDay, setSelectedDay] = useState(A.today >= 0 ? A.today : 0);
  const [confirmSheet, setConfirmSheet] = useState<{
    slot: AgendaSlot;
    item?: DraggedItem | undefined;
  } | null>(null);

  const currentA = computeWeek(A, weekOffset);
  const EV = eventsOf(currentA, ui.booked);
  const find = findRuleOf(currentA)?.find;
  const joins = EV.filter((e) => joinsOf(e, ui.flags) && !e.past).length;
  const shown = EV.filter((e) => !e.tiloOnly && e.cal !== "tilo").length;

  const titleText =
    weekOffset === 0
      ? `This week · ${weekRange(A, ui.weekend)}${A.rules ? ` ${A.rules.month}` : ""}`
      : `Week of ${currentA.days[0]} · ${weekRange(currentA, ui.weekend)}${A.rules ? ` ${A.rules.month}` : ""}`;

  return (
    <section aria-label="This week" className="park-agenda-section">
      <div className="park-agenda-topbar">
        <div
          className="park-agenda-topbar-left"
          style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}
        >
          <button
            type="button"
            className="park-agenda-create-btn"
            onClick={ui.findTime}
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
                setWeekOffset(0);
                setSelectedDay(A.today >= 0 ? A.today : 0);
              }}
            >
              Today
            </button>
            <button
              type="button"
              className="park-agenda-navbtn"
              aria-label="Previous week"
              onClick={() => setWeekOffset((w) => w - 1)}
            >
              ‹
            </button>
            <button
              type="button"
              className="park-agenda-navbtn"
              aria-label="Next week"
              onClick={() => setWeekOffset((w) => w + 1)}
            >
              ›
            </button>
          </div>
          <h2 className="park-agenda-h2 park-agenda-month-title">{titleText}</h2>
        </div>
        <div className="park-agenda-weekactions">
          <div className="park-agenda-viewswitch" role="radiogroup" aria-label="Calendar view">
            {(["day", "week", "month"] as const).map((m) => (
              <button
                key={m}
                type="button"
                // biome-ignore lint/a11y/useSemanticElements: view switcher radio buttons
                role="radio"
                aria-checked={viewMode === m}
                className={`park-agenda-viewbtn${viewMode === m ? " is-active" : ""}`}
                onClick={() => setViewMode(m)}
              >
                {m.charAt(0).toUpperCase() + m.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="park-agenda-secsub">
        {`${shown} events from Google Calendar · Tilo joins ${joins} still to come`}
      </div>

      {ui.finding && find ? (
        <div className="park-agenda-find">
          <div className="park-agenda-findface">
            {face({ role: "research", expr: "focused" }, 40, app.night)}
          </div>
          <div className="park-agenda-findtext">
            <div className="park-agenda-findtitle">{find.title}</div>
            <div className="park-agenda-findsub">{find.sub}</div>
          </div>
          <button type="button" className="park-agenda-cancel" onClick={ui.cancelFind}>
            Cancel
          </button>
        </div>
      ) : null}

      <div
        className="park-agenda-weekgrid"
        data-week-grid=""
        style={{ gridTemplateColumns: app.vw >= 1100 ? "minmax(0,1fr) 340px" : "minmax(0,1fr)" }}
      >
        <div
          className="park-agenda-layout"
          style={{
            display: "flex",
            gap: "16px",
            alignItems: "flex-start",
            width: "100%",
            minWidth: 0,
            flexWrap: app.vw <= 600 ? "wrap" : "nowrap",
          }}
        >
          <aside
            className="park-agenda-sidebar"
            aria-label="Calendar sidebar"
            style={{ flex: app.vw <= 600 ? "1 1 100%" : "0 0 200px", minWidth: 0 }}
          >
            <details className="park-agenda-minidropdown" open={app.vw > 600}>
              <summary className="park-agenda-minidropdown-summary">
                {A.rules?.month ??
                  new Intl.DateTimeFormat(undefined, {
                    month: "long",
                    year: "numeric",
                  }).format(new Date())}
              </summary>
              <MiniMonth
                weekOffset={weekOffset}
                onSelectOffset={(offset) => {
                  setWeekOffset(offset);
                }}
              />
            </details>
            <section className="park-agenda-mycals" aria-label="My calendars">
              <h3 className="park-agenda-mycals-title">My calendars</h3>
              <div className="park-agenda-mycals-list">
                {FILTERS.map((k) => (
                  <button
                    key={k}
                    type="button"
                    className="park-agenda-filter park-agenda-calcheck"
                    aria-pressed={ui.cals[k]}
                    style={{
                      opacity: ui.cals[k] ? 1 : 0.6,
                      background: "transparent",
                      border: "none",
                      padding: "4px 0",
                      display: "flex",
                      alignItems: "center",
                      gap: "10px",
                      cursor: "pointer",
                    }}
                    onClick={() => ui.toggleCal(k)}
                  >
                    <span
                      className="park-agenda-calcheck-box"
                      data-event-tone={k}
                      style={{
                        background: CAL[k][1],
                        width: 14,
                        height: 14,
                        borderRadius: 3,
                        boxShadow: ui.cals[k] ? "inset 0 0 0 2px var(--card)" : "none",
                      }}
                    />
                    <span
                      className="park-agenda-calcheck-text"
                      style={{ color: "var(--ink)", fontWeight: 600, fontSize: 13 }}
                    >
                      {CAL[k][0]}
                    </span>
                  </button>
                ))}
                <button
                  type="button"
                  className="park-agenda-filter park-agenda-filter--weekend park-agenda-calcheck"
                  aria-pressed={ui.weekend}
                  style={{
                    opacity: ui.weekend ? 1 : 0.6,
                    background: "transparent",
                    border: "none",
                    padding: "4px 0",
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                    cursor: "pointer",
                  }}
                  onClick={ui.toggleWeekend}
                >
                  <span
                    className="park-agenda-calcheck-box"
                    style={{
                      background: ui.weekend ? "var(--toast)" : "var(--btn2)",
                      width: 14,
                      height: 14,
                      borderRadius: 3,
                    }}
                  />
                  <span
                    className="park-agenda-calcheck-text"
                    style={{ color: "var(--ink)", fontWeight: 600, fontSize: 13 }}
                  >
                    Weekend
                  </span>
                </button>
              </div>
            </section>
          </aside>
          <div className="park-agenda-main" style={{ flex: "1 1 0", minWidth: 0 }}>
            {viewMode === "month" ? (
              <MonthView
                A={currentA}
                EV={EV}
                ui={ui}
                onSelectDay={(d) => {
                  setSelectedDay(d);
                  setViewMode("day");
                }}
              />
            ) : (
              <Calendar
                A={currentA}
                EV={EV}
                ui={ui}
                app={app}
                weekOffset={weekOffset}
                viewMode={viewMode}
                selectedDay={selectedDay}
                onConfirmSlot={(slot, item) => setConfirmSheet({ slot, item })}
              />
            )}
          </div>
        </div>
        <Detail
          vm={detailOf(currentA, EV, ui.sel, ui.flags, ui.briefed, app.dec)}
          ui={ui}
          app={app}
        />
      </div>

      {confirmSheet ? (
        <ModalScrim onClose={() => setConfirmSheet(null)}>
          {/* biome-ignore lint/a11y/useSemanticElements: modal dialog container */}
          <div className="park-agenda-confirmsheet" role="dialog" aria-label="Confirm schedule">
            <h3 className="park-agenda-confirmtitle">Confirm scheduling</h3>
            <p className="park-agenda-confirmdesc">
              {confirmSheet.item
                ? `Schedule "${confirmSheet.item.title}" at ${confirmSheet.slot.l}?`
                : `Schedule meeting at ${confirmSheet.slot.l}?`}
            </p>
            <p className="park-agenda-confirmmeta">
              Time: {fmt(confirmSheet.slot.s)}–{fmt(confirmSheet.slot.e)}
            </p>
            <div className="park-agenda-confirmbtns">
              <Button
                variant="primary"
                onClick={() => {
                  const s = confirmSheet.slot;
                  setConfirmSheet(null);
                  void ui.book(s);
                }}
              >
                Confirm
              </Button>
              <Button variant="secondary" onClick={() => setConfirmSheet(null)}>
                Cancel
              </Button>
            </div>
          </div>
        </ModalScrim>
      ) : null}
    </section>
  );
}
