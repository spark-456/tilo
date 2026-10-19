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
  for (let t = START_HOUR + 1; t < END_HOUR; t++) hours.push(t);

  const dragSlot = useRef<AgendaSlot | null>(null);

  const now = new Date();
  const currentHour = now.getHours() + now.getMinutes() / 60;
  const nowPos =
    currentHour >= START_HOUR && currentHour <= END_HOUR
      ? (currentHour - START_HOUR) * PX
      : ((A.now ?? 9.2) - START_HOUR) * PX;

  return (
    <div className="park-agenda-cal">
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
                className="park-agenda-daynum"
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
            {d.events.map((e) => {
              const [, bar, bg, fg] = CAL[e.cal];
              const on = ui.sel === e.id;
              const tall = e.e - e.s >= 0.75;
              const style: CSSProperties = {
                top: (e.s - START_HOUR) * PX + 1,
                height: Math.max(20, (e.e - e.s) * PX - 3),
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
                    <span className="park-agenda-eventtitle">{e.t}</span>
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
              {d.events.slice(0, 2).map((e) => (
                <div key={e.id} className="park-agenda-monthtag">
                  {e.t}
                </div>
              ))}
              {d.events.length > 2 ? (
                <span className="park-agenda-monthmore">+{d.events.length - 2} more</span>
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
  const [viewMode, setViewMode] = useState<"day" | "week" | "month">("week");
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
      <div className="park-agenda-sechead">
        <div>
          <h2 className="park-agenda-h2">{titleText}</h2>
          <div className="park-agenda-secsub">
            {`${shown} events from Google Calendar · Tilo joins ${joins} still to come`}
          </div>
        </div>
        <div className="park-agenda-filters">
          {/* biome-ignore lint/a11y/useSemanticElements: a labelled group of calendar controls, not a form fieldset */}
          <div className="park-agenda-nav" role="group" aria-label="Calendar navigation">
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
              aria-label="Next week"
              onClick={() => setWeekOffset((w) => w + 1)}
            >
              ›
            </button>
          </div>
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
          {FILTERS.map((k) => (
            <button
              key={k}
              type="button"
              className="park-agenda-filter"
              aria-pressed={ui.cals[k]}
              style={{ opacity: ui.cals[k] ? 1 : 0.5 }}
              onClick={() => ui.toggleCal(k)}
            >
              <span className="park-agenda-swatch" style={{ background: CAL[k][1] }} />
              {CAL[k][0]}
            </button>
          ))}
          <button
            type="button"
            className="park-agenda-filter park-agenda-filter--weekend"
            aria-pressed={ui.weekend}
            style={
              ui.weekend
                ? { background: "var(--toast)", color: "var(--toastInk)" }
                : { background: "var(--btn2)", color: "var(--ink)" }
            }
            onClick={ui.toggleWeekend}
          >
            Weekend
          </button>
        </div>
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
