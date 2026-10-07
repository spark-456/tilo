// The Boards section (reference: the `Boards` region of Tilo App Agenda.dc.html): a team board and a
// personal board, each as sticky notes on cork or as grouped rows. Every approval is read from `app.dec`;
// opening a world goes through `app.go`.
import type { CSSProperties } from "react";
import type { Agenda, AgendaPin } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { SegmentedControl } from "../../components";
import { face, icon } from "./icons";
import { BOARDS, type BoardKey, GROUPS, PERSON, type PinVm, boardSub, pinVm } from "./model";
import type { AgendaUi } from "./useAgenda";

interface PinProps {
  v: PinVm;
  ui: AgendaUi;
  app: AppCtx;
}

function Avatar({ v, size, night }: { v: PinVm; size: number; night: boolean }) {
  return v.avatar ? face(v.avatar, size, night) : v.pin.by;
}

function toggle(v: PinVm, ui: AgendaUi, app: AppCtx) {
  const p = v.pin;
  if (p.dec) {
    if (!app.dec[p.dec] && v.act) app.go("world", { id: v.act.world });
    return;
  }
  ui.setDone(p.id, !v.done);
}

function Accept({ v, ui, soft }: PinProps & { soft?: boolean }) {
  const p = v.pin;
  const rule = ui.ruleOf(p);
  return (
    <>
      <button
        type="button"
        className={soft ? "park-agenda-accept park-agenda-accept--soft" : "park-agenda-accept"}
        onClick={() => (rule.action === "find" ? ui.findTime() : ui.accept(p))}
      >
        {rule.label}
      </button>
      <button
        type="button"
        className={soft ? "park-agenda-notnow park-agenda-notnow--soft" : "park-agenda-notnow"}
        onClick={() => ui.dismiss(p.id)}
      >
        Not now
      </button>
    </>
  );
}

function ActButton({ v, app, soft }: { v: PinVm; app: AppCtx; soft?: boolean }) {
  if (!v.act) return null;
  const { label, world } = v.act;
  return (
    <button
      type="button"
      className={soft ? "park-agenda-act park-agenda-act--soft" : "park-agenda-act"}
      onClick={() => app.go("world", { id: world })}
    >
      {label}
    </button>
  );
}

function CorkPin({ v, ui, app }: PinProps) {
  const p = v.pin;
  const style = {
    "--rot": v.rot,
    background: v.paper,
    opacity: v.done ? 0.62 : 1,
  } as CSSProperties;
  return (
    <div
      className={`park-agenda-pin${p.suggested ? " park-agenda-pin--suggested" : ""}`}
      data-pin={p.id}
      style={style}
    >
      <span className="park-agenda-tack" style={{ background: v.tilo ? "#5A3FE0" : "#E2483D" }} />
      {p.suggested ? <span className="park-agenda-suggests">TILO SUGGESTS</span> : null}
      <div
        className="park-agenda-pintitle"
        style={{ textDecoration: v.done ? "line-through" : "none" }}
      >
        {p.title}
      </div>
      <div className="park-agenda-pinnote">{v.note}</div>
      <div className="park-agenda-grow" />
      {p.suggested ? (
        <div className="park-agenda-pinbtns">
          <Accept v={v} ui={ui} app={app} />
        </div>
      ) : null}
      <ActButton v={v} app={app} />
      {p.suggested ? null : (
        <div className="park-agenda-pinfoot">
          <span
            className="park-agenda-pinav"
            style={{ alignItems: v.tilo ? "flex-end" : "center" }}
          >
            <Avatar v={v} size={26} night={app.night} />
          </span>
          <span className="park-agenda-pindue">{v.due}</span>
          <button
            type="button"
            className="park-agenda-check"
            aria-label={v.checkLabel}
            style={{ background: v.done ? "#1E8A4C" : "transparent" }}
            onClick={() => toggle(v, ui, app)}
          >
            {v.done ? icon("check", 12) : null}
          </button>
        </div>
      )}
    </div>
  );
}

function SoftPin({ v, ui, app }: PinProps) {
  const p = v.pin;
  const bg = p.suggested ? "var(--heroSoft)" : v.waiting ? "var(--amberSoft)" : "var(--sunk)";
  const bd = p.suggested
    ? "1.5px dashed var(--hero)"
    : v.waiting
      ? "1px solid var(--amberLine)"
      : "1px solid transparent";
  return (
    <div
      className="park-agenda-soft"
      data-pin={p.id}
      style={{ background: bg, border: bd, opacity: v.done ? 0.62 : 1 }}
    >
      <span className="park-agenda-accent" style={{ background: v.accent }} />
      <div className="park-agenda-softbody">
        <span
          className="park-agenda-softtitle"
          style={{ textDecoration: v.done ? "line-through" : "none" }}
        >
          {p.title}
        </span>
        <span className="park-agenda-softnote">{v.note}</span>
        {p.suggested ? (
          <span className="park-agenda-softbtns">
            <Accept v={v} ui={ui} app={app} soft />
          </span>
        ) : (
          <span className="park-agenda-softmeta">
            <span
              className="park-agenda-softdue"
              style={{ color: v.waiting ? "var(--amberInk)" : "var(--ink3)" }}
            >
              {v.due}
            </span>
            <ActButton v={v} app={app} soft />
          </span>
        )}
      </div>
      {p.suggested ? null : (
        <div className="park-agenda-softside">
          <span
            className="park-agenda-softav"
            style={{
              background: v.tilo ? "var(--heroSoft)" : (PERSON[p.by] ?? "#E6E1F8"),
              alignItems: v.tilo ? "flex-end" : "center",
            }}
          >
            <Avatar v={v} size={26} night={app.night} />
          </span>
          <button
            type="button"
            className="park-agenda-softcheck"
            aria-label={v.checkLabel}
            style={{
              borderColor: v.done ? "var(--ok)" : "var(--line)",
              background: v.done ? "var(--ok)" : "var(--card)",
            }}
            onClick={() => toggle(v, ui, app)}
          >
            {v.done ? icon("check", 12) : null}
          </button>
        </div>
      )}
    </div>
  );
}

function Board({
  A,
  k,
  ui,
  app,
  limit,
}: { A: Agenda; k: BoardKey; ui: AgendaUi; app: AppCtx; limit: number }) {
  const b = BOARDS.find((x) => x.key === k) ?? BOARDS[0];
  if (!b) return null;
  const ps: AgendaPin[] = ui.pins.filter((p) => p.board === k);
  const vms = ps.map((p, i) => pinVm(p, i, app.dec, ui.done, ui.decisions));
  const open = vms.filter((v) => !v.done && !v.pin.suggested).length;
  const shown = vms.slice(0, limit); // the pins are drawn a few tasks at a time (WEB-MOTION-2), top to bottom
  const label = `Pin to ${b.title}`;
  const input = (cls: string) => (
    <input
      aria-label={label}
      className={cls}
      value={ui.newVal[k]}
      placeholder="Pin something…"
      onChange={(e) => ui.setNewVal(k, e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") ui.add(k);
      }}
    />
  );
  return (
    <div className="park-agenda-board" data-board={k}>
      <div className="park-agenda-boardhead">
        <div className="park-agenda-boardicon" style={{ background: b.iconBg }}>
          {face(b.agent, 38, app.night)}
        </div>
        <div className="park-agenda-boardtitles">
          <div className="park-agenda-boardtitle">{b.title}</div>
          <div className="park-agenda-boardsub">{boardSub(A, b)}</div>
        </div>
        <span className="park-agenda-boardcount">{`${open} open`}</span>
      </div>
      {ui.style === "cork" ? (
        <div className="park-agenda-cork">
          {shown.map((v) => (
            <CorkPin key={v.pin.id} v={v} ui={ui} app={app} />
          ))}
          {shown.length === vms.length ? (
            // After the last pin: this row sits below the pins, so it appears once they are all drawn instead of
            // being pushed down by each one (no layout shift while the board stages).
            <div className="park-agenda-newpin">
              {input("park-agenda-newinput")}
              <button type="button" className="park-agenda-pinit" onClick={() => ui.add(k)}>
                Pin it
              </button>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="park-agenda-grouped">
          <div className="park-agenda-addrow">
            {icon("plus", 13)}
            {input("park-agenda-addinput")}
            <button type="button" className="park-agenda-addbtn" onClick={() => ui.add(k)}>
              Pin
            </button>
          </div>
          {GROUPS.map(([title, f]) => {
            const list = shown.filter(f);
            return list.length ? (
              <div key={title} className="park-agenda-group">
                <div className="park-agenda-grouptitle">{`${title} · ${list.length}`}</div>
                {list.map((v) => (
                  <SoftPin key={v.pin.id} v={v} ui={ui} app={app} />
                ))}
              </div>
            ) : null;
          })}
        </div>
      )}
    </div>
  );
}

export function Boards({
  A,
  ui,
  app,
  limit,
}: { A: Agenda; ui: AgendaUi; app: AppCtx; limit: number }) {
  return (
    <section aria-label="Boards" className="park-agenda-section">
      <div className="park-agenda-sechead">
        <div>
          <h2 className="park-agenda-h2">Boards</h2>
          <div className="park-agenda-secsub">
            Anyone on the team can pin. Tilo pins action items from meetings and things that need
            you.
          </div>
        </div>
        <div className="park-agenda-styleseg">
          <SegmentedControl
            label="Board style"
            sliding
            size="lg"
            options={[
              { value: "cork", label: "Pinboard" },
              { value: "soft", label: "Grouped", tone: "ink" },
            ]}
            value={ui.style}
            onChange={(v) => ui.setStyle(v === "soft" ? "soft" : "cork")}
          />
        </div>
      </div>
      <div className="park-agenda-boards">
        {BOARDS.map((b) => (
          <Board key={b.key} A={A} k={b.key} ui={ui} app={app} limit={limit} />
        ))}
      </div>
    </section>
  );
}
