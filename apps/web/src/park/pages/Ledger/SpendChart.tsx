import { type MouseEvent, useState } from "react";
import type { Dec, Ledger } from "../../api/types";
import { chartGeometry, dayFromX, money, periodOf } from "./model";

/** Spend over the month: the SVG 720x270 chart, its labels and the hover tooltip. */
export function SpendChart({ L, dec }: { L: Ledger; dec: Dec }) {
  const [hover, setHover] = useState<number | null>(null);
  const c = chartGeometry(L, dec, hover);
  const move = (e: MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (!r.width) return;
    const d = dayFromX((e.clientX - r.left) / r.width, periodOf(L).days);
    if (d !== hover) setHover(d);
  };
  return (
    <div
      className="park-ledger-chart"
      data-chart=""
      onMouseMove={move}
      onMouseLeave={() => setHover(null)}
    >
      <svg
        className="park-ledger-svg"
        viewBox="0 0 720 270"
        width="100%"
        height="100%"
        role="img"
        aria-label={`Running total of spend for ${periodOf(L).month}, with a forecast to the month end`}
      >
        <path className="park-ledger-p-grid" d={c.grid} />
        <path className="park-ledger-p-pace" d={c.pace} />
        <path className="park-ledger-p-cap" d={c.cap} />
        <path className="park-ledger-p-area" d={c.area} />
        <path className="park-ledger-p-fc" d={c.fc} />
        <path className="park-ledger-p-line" d={c.line} />
        <path className="park-ledger-p-today" d={c.today} />
        <circle className="park-ledger-p-now" cx={c.nowX} cy={c.nowY} r="5.5" />
        <circle className="park-ledger-p-end" cx={c.endX} cy={c.endY} r="4.5" />
        <path className="park-ledger-p-hline" d={c.hLine} opacity={c.hOp} />
        <circle className="park-ledger-p-hdot" cx={c.hx} cy={c.hy} r="5" opacity={c.hOp} />
      </svg>
      {c.yLabels.map((l) => (
        <span key={l.t} className="park-ledger-ylabel" style={{ top: l.top }}>
          {l.t}
        </span>
      ))}
      {c.xLabels.map((l) => (
        <span key={l.t} className="park-ledger-xlabel" style={{ left: l.left }}>
          {l.t}
        </span>
      ))}
      <span className="park-ledger-note park-ledger-note--cap" style={{ top: c.capTop }}>
        Budget {money(L, L.budget)}
      </span>
      {c.spike ? (
        <span
          className="park-ledger-note park-ledger-note--spike"
          style={{ left: c.spike.left, top: c.spike.top }}
        >
          {c.spike.text}
        </span>
      ) : null}
      <span
        className="park-ledger-note park-ledger-note--fc"
        style={{ left: c.fcLeft, top: c.fcTop }}
      >
        {c.fcLabel}
      </span>
      <div
        className="park-ledger-tip"
        data-tip=""
        style={{ left: c.tipLeft, opacity: Number(c.hOp) }}
        aria-hidden="true"
      >
        <div>{c.tipA}</div>
        <div>{c.tipB}</div>
      </div>
    </div>
  );
}
