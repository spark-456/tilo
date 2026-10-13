// The "This week" section (reference: the `This week` and `Event detail` regions of Tilo App Agenda.dc.html):
// calendar filters, the find-a-time banner, the week grid with its dashed slots, and the detail aside.
import type { CSSProperties } from "react";
import type { Agenda } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
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

function Calendar({ A, EV, ui, app }: { A: Agenda; EV: Ev[]; ui: AgendaUi; app: AppCtx }) {
  const days = dayColumns(A, EV, ui.cals, ui.weekend, ui.finding);
  const cols = `50px repeat(${days.length},minmax(0,1fr))`;
  const hours: number[] = [];
  for (let t = A.start + 1; t < A.end; t++) hours.push(t);
  return (
    <div className="park-agenda-cal">
      <div className="park-agenda-calhead" style={{ gridTemplateColumns: cols }}>
        <div />
        {days.map((d) => (
          <div
            key={d.name}
            className="park-agenda-dayhead"
            style={{ background: d.today ? "var(--heroSoft)" : "transparent" }}
          >
            <div className="park-agenda-dayline">
              <span
                className="park-agenda-dayname"
                style={{ color: d.today ? "var(--heroInk)" : "var(--ink3)" }}
              >
                {d.name}
              </span>
              <span
                className="park-agenda-daynum"
                style={{
                  background: d.today ? "var(--heroFill)" : "transparent",
                  color: d.today ? "#FFFFFF" : "var(--ink)",
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
        style={{ gridTemplateColumns: cols, height: (A.end - A.start) * PX }}
      >
        <div className="park-agenda-hours">
          {hours.map((t) => (
            <div key={t} className="park-agenda-hour" style={{ top: (t - A.start) * PX }}>
              {fmt(t)}
            </div>
          ))}
        </div>
        {days.map((d) => (
          <div
            key={d.name}
            className="park-agenda-col"
            style={{
              backgroundColor: d.today ? "var(--rowOn)" : d.weekend ? "var(--sunk)" : "transparent",
            }}
          >
            {d.events.map((e) => {
              const [, bar, bg, fg] = CAL[e.cal];
              const on = ui.sel === e.id;
              const tall = e.e - e.s >= 0.75;
              const style: CSSProperties = {
                top: (e.s - A.start) * PX + 1,
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
                // At least 24 px tall: a 30 minute slot is 23 px at PX 52 (WCAG 2.5.8).
                style={{
                  top: (s.s - A.start) * PX + 1,
                  height: Math.max(24, (s.e - s.s) * PX - 3),
                }}
                onClick={() => void ui.book(s)}
              >
                {icon("plus", 13)}
                {`${fmt(s.s)} · all free`}
              </button>
            ))}
            {d.today ? (
              <div className="park-agenda-now" style={{ top: (A.now - A.start) * PX }}>
                <span className="park-agenda-nowdot" />
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

export function Week({ A, ui, app }: { A: Agenda; ui: AgendaUi; app: AppCtx }) {
  const EV = eventsOf(A, ui.booked);
  const find = findRuleOf(A)?.find;
  const joins = EV.filter((e) => joinsOf(e, ui.flags) && !e.past).length;
  const shown = EV.filter((e) => !e.tiloOnly && e.cal !== "tilo").length;
  return (
    <section aria-label="This week" className="park-agenda-section">
      <div className="park-agenda-sechead">
        <div>
          <h2 className="park-agenda-h2">{`This week · ${weekRange(A, ui.weekend)}${A.rules ? ` ${A.rules.month}` : ""}`}</h2>
          <div className="park-agenda-secsub">
            {`${shown} events from Google Calendar · Tilo joins ${joins} still to come`}
          </div>
        </div>
        <div className="park-agenda-filters">
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
        <Calendar A={A} EV={EV} ui={ui} app={app} />
        <Detail vm={detailOf(A, EV, ui.sel, ui.flags, ui.briefed, app.dec)} ui={ui} app={app} />
      </div>
    </section>
  );
}
