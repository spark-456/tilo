// The Ledger page (WEB-7): every cost and every decision the agents make. Pixel port of
// design_handoff_tilo_web_app/design/Tilo App Ledger.dc.html (user's prototype, ADR-0003a).
// Data comes only from the Park Api (fixture or live, with its `source`); every approval goes through
// `app.decide(key)`; navigation only through `app.go`. No motion until WEB-3 (BQ-WEB-3).
import type { ReactNode } from "react";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi } from "../../app/context";
import { useStaged } from "../../app/useStaged";
import { Button, KpiTile, PageSheet } from "../../components";
import "../../components/park.components.css";
import { Activity } from "./Activity";
import { ApprovalWaits, CostPerRun, GaveBack, WhereItGoes } from "./Sections";
import { SpendChart } from "./SpendChart";
import { icon } from "./icons";
import { gbp, groupsWithRows, hasChart, hasWaits, kpis, monthLeft } from "./model";
import { useLedger } from "./useLedger";
import "./Ledger.css";

export interface LedgerPageProps {
  app: AppCtx;
}

function Frame({ source, children }: { source?: string; children?: ReactNode }) {
  return (
    <div
      className="park-ledger-root"
      data-testid="park-page-ledger"
      data-park-ledger=""
      data-source={source}
    >
      <PageSheet gap={20}>{children}</PageSheet>
    </div>
  );
}

export function LedgerPage({ app }: LedgerPageProps) {
  const state = useLedger(useParkApi());
  const part = useStaged(5); // drawn top to bottom, one task each, so the page never holds the thread

  if (state.status === "not-built" || state.status === "error") {
    return (
      <Frame>
        <div className="park-ledger-state">
          <h1 className="park-ledger-title">Ledger</h1>
          <div className="park-ledger-state-title">
            {state.status === "not-built" ? "Not connected yet" : "The Ledger could not load"}
          </div>
          <div className="park-ledger-state-line">
            {state.status === "not-built"
              ? "Spend and decisions show here once the Ledger is connected."
              : "Try again in a moment."}
          </div>
        </div>
      </Frame>
    );
  }
  if (state.status === "loading") return <Frame />;

  const L = state.data;
  const wide = app.vw >= 1100;
  // What the Ledger holds no data for is left out, not shown as a sample or a zero (HR-1..HR-7).
  const chart = hasChart(L);
  const where = groupsWithRows(L).length > 0;
  const lede = [monthLeft(L), L.budget > 0 ? `budget ${gbp(L.budget)}` : null].filter(Boolean);
  const month = monthLeft(L) !== null;
  return (
    <Frame source={state.source}>
      <div className="park-ledger-head">
        <div className="park-ledger-titles">
          <h1 className="park-ledger-title">Ledger</h1>
          <p className="park-ledger-lede">
            {`Every cost and every decision your agents make.${lede.length ? ` ${lede.join(" · ")}.` : ""}`}
          </p>
        </div>
        {month ? (
          <div className="park-ledger-actions">
            <span className="park-ledger-month">
              <Button
                variant="secondary"
                onClick={() => app.toast("August and earlier months live here")}
              >
                September 2026
                {icon("chevD", 13)}
              </Button>
            </span>
            <Button
              variant="secondary"
              icon={icon("download", 15)}
              onClick={() => app.toast("Exported september-2026.csv · also synced to Xero")}
            >
              Export CSV
            </Button>
          </div>
        ) : null}
      </div>

      <div className="park-ledger-kpis">
        {kpis(L, app.dec, state.decisions).map((k) => (
          <KpiTile
            key={k.label}
            label={k.label}
            value={k.value}
            {...(k.sub ? { sub: k.sub } : {})}
            {...(k.tone ? { tone: k.tone } : {})}
            {...(k.opensWorld
              ? { onClick: () => app.go("world", { id: k.opensWorld ?? "" }) }
              : {})}
          />
        ))}
      </div>

      {part(2) && (chart || where) ? (
        <div
          className="park-ledger-chartrow"
          data-chart-row=""
          style={{
            gridTemplateColumns:
              wide && chart && where ? "minmax(0,1.65fr) minmax(320px,1fr)" : "minmax(0,1fr)",
          }}
        >
          {chart ? (
            <section
              aria-label="Spend over the month"
              className="park-ledger-card park-ledger-card--chart"
            >
              <div className="park-ledger-charthead">
                <div>
                  <div className="park-ledger-eyebrow">SPEND OVER TIME</div>
                  <h2 className="park-ledger-h2">
                    {`On track to finish ${gbp(L.budget - L.forecast)} under budget`}
                  </h2>
                  <div className="park-ledger-sub">
                    Running total for September. Hover for daily spend.
                  </div>
                </div>
                <div className="park-ledger-legend">
                  <span>
                    <span className="park-ledger-key park-ledger-key--spent" />
                    Spent
                  </span>
                  <span>
                    <span className="park-ledger-key park-ledger-key--forecast" />
                    Forecast
                  </span>
                  <span>
                    <span className="park-ledger-key park-ledger-key--pace" />
                    Even pace
                  </span>
                </div>
              </div>
              <SpendChart L={L} dec={app.dec} />
            </section>
          ) : null}
          {where ? <WhereItGoes L={L} /> : null}
        </div>
      ) : null}

      {part(3) && (L.runs.length > 0 || hasWaits(L)) ? (
        <div className="park-ledger-pair">
          {L.runs.length > 0 ? <CostPerRun L={L} go={app.go} /> : null}
          {hasWaits(L) ? <ApprovalWaits L={L} app={app} /> : null}
        </div>
      ) : null}

      {part(4) && (L.memory.length > 0 || L.hours.length > 0) ? <GaveBack L={L} /> : null}
      {part(5) && L.activity.length > 0 ? (
        <Activity L={L} decisions={state.decisions} app={app} />
      ) : null}
    </Frame>
  );
}
