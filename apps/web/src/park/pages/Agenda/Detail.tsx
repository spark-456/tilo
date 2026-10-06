// The event detail aside (reference: the `Event detail` region of Tilo App Agenda.dc.html): who is
// there, Tilo's brief, notes and follow-ups of a past meeting, and the three switches of an upcoming one.
import type { AppCtx } from "./appCtx";
import { face } from "./icons";
import { CAL, type DetailVm, PERSON } from "./model";
import type { AgendaUi } from "./useAgenda";

export function Detail({ vm, ui, app }: { vm: DetailVm; ui: AgendaUi; app: AppCtx }) {
  const { e, det } = vm;
  const joins = vm.toggles[0]?.[2] ?? false;
  return (
    <aside aria-label="Event detail" className="park-agenda-detail">
      <div className="park-agenda-detailhead">
        <div className="park-agenda-detailcal">
          <span className="park-agenda-swatch" style={{ background: CAL[e.cal][1] }} />
          <span className="park-agenda-detailcallabel">{vm.calLabel}</span>
        </div>
        <div className="park-agenda-detailtitle">{e.t}</div>
        <div className="park-agenda-detailwhen">{vm.when}</div>
      </div>
      <div className="park-agenda-people">
        {det.people.map((i) => (
          <span
            key={i}
            className="park-agenda-person"
            style={{ background: PERSON[i] ?? "#EDEBE4" }}
          >
            {i}
          </span>
        ))}
        {joins ? (
          <span className="park-agenda-person park-agenda-person--tilo">
            {face({ rank: "director", expr: "talking" }, 28, app.night)}
          </span>
        ) : null}
      </div>
      {vm.hasBrief ? (
        <div className="park-agenda-brief">
          <div className="park-agenda-briefhead">
            <span className="park-agenda-briefname">TILO’S BRIEF</span>
            <span className="park-agenda-briefmeta">{vm.briefMeta}</span>
          </div>
          {vm.brief.map((t) => (
            <div key={t} className="park-agenda-bullet">
              <span className="park-agenda-dot" />
              <span>{t}</span>
            </div>
          ))}
        </div>
      ) : null}
      {vm.needsBrief ? (
        <button
          type="button"
          className="park-agenda-askbrief"
          onClick={() => ui.askBrief(e.id, e.t)}
        >
          Ask Tilo for a brief
        </button>
      ) : null}
      {vm.past ? (
        <div className="park-agenda-notes">
          <div className="park-agenda-eyebrow">NOTES BY TILO</div>
          {(det.notes ?? []).map((t) => (
            <div key={t} className="park-agenda-note">
              {t}
            </div>
          ))}
          <div className="park-agenda-eyebrow park-agenda-eyebrow--gap">FOLLOW-UPS</div>
          {(det.actions ?? []).map(([t, who, s]) => (
            <div key={t} className="park-agenda-action">
              <span
                className="park-agenda-actionwho"
                style={{
                  background: who === "tilo" ? "var(--heroSoft)" : (PERSON[who] ?? "#EDEBE4"),
                  alignItems: who === "tilo" ? "flex-end" : "center",
                }}
              >
                {who === "tilo"
                  ? face({ role: "delivery", expr: "delighted" }, 24, app.night)
                  : who}
              </span>
              <span className="park-agenda-actiontext">
                <span className="park-agenda-actiontitle">{t}</span>
                <span className="park-agenda-actionsub">{s}</span>
              </span>
            </div>
          ))}
        </div>
      ) : null}
      {vm.empty ? <div className="park-agenda-empty">No notes for this one.</div> : null}
      {vm.upcoming ? (
        <div className="park-agenda-toggles">
          {vm.toggles.map(([label, sub, on, k]) => (
            <button
              key={k}
              type="button"
              role="switch"
              aria-checked={on}
              className="park-agenda-toggle"
              onClick={() => ui.flip(e.id, k, on, e.t)}
            >
              <span className="park-agenda-toggletext">
                <span className="park-agenda-togglelabel">{label}</span>
                <span className="park-agenda-togglesub">{sub}</span>
              </span>
              <span
                className="park-agenda-track"
                style={{ background: on ? "var(--ok)" : "var(--track)" }}
              >
                <span
                  className="park-agenda-knob"
                  style={{ transform: on ? "translateX(18px)" : "none" }}
                />
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </aside>
  );
}
