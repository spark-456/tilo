// The Agenda page (WEB-9): pins from the team and Tilo, and a week that stays in sync. Pixel port of
// design_handoff_tilo_web_app/design/Tilo App Agenda.dc.html (user's prototype, ADR-0003a).
// Data comes only from the Park Api (fixture or live, with its `source`); the page reads approvals from
// `app.dec` (the shell's `decide(key)` is the only way one changes); navigation only through `app.go`.
// No motion until WEB-3 (BQ-WEB-3).
import type { ReactNode } from "react";
import type { Api } from "../../api/index";
import type { Agenda } from "../../api/types";
import { Button, PageSheet } from "../../components";
import "../../components/park.components.css";
import { Boards } from "./Boards";
import { Week } from "./Week";
import type { AppCtx } from "./appCtx";
import { icon } from "./icons";
import { useAgenda, useAgendaUi } from "./useAgenda";
import { useParkApi } from "./useParkApi";
import "./Agenda.css";

export interface AgendaPageProps {
  app: AppCtx;
  /** Tests inject an Api; the page otherwise reads the shared Park Api. */
  api?: Api;
}

function Frame({ source, children }: { source?: string; children?: ReactNode }) {
  return (
    <div className="park-agenda-root" data-park-agenda="" data-source={source}>
      <PageSheet gap={30}>{children}</PageSheet>
    </div>
  );
}

function Ready({ A, app, api }: { A: Agenda; app: AppCtx; api: Api }) {
  const ui = useAgendaUi(A, app, api);
  return (
    <>
      <div className="park-agenda-head">
        <div className="park-agenda-titles">
          <h1 className="park-agenda-title">Agenda</h1>
          <p className="park-agenda-lede">
            Thursday 24 September. Pins from your team and Tilo, and a week that stays in sync.
          </p>
        </div>
        <div className="park-agenda-actions">
          <div className="park-agenda-synced">
            <span className="park-agenda-synced-tick">{icon("check", 13)}</span>
            Google Calendar · synced just now
          </div>
          <Button variant="primary" icon={icon("calendar", 16)} onClick={ui.findTime}>
            Find a time
          </Button>
        </div>
      </div>
      <Boards ui={ui} app={app} />
      <Week A={A} ui={ui} app={app} />
    </>
  );
}

export function AgendaPage({ app, api }: AgendaPageProps) {
  const shared = useParkApi();
  const use = api ?? shared;
  const state = useAgenda(use);

  if (state.status === "not-built" || state.status === "error") {
    return (
      <Frame>
        <div className="park-agenda-state">
          <h1 className="park-agenda-title">Agenda</h1>
          <div className="park-agenda-state-title">
            {state.status === "not-built" ? "Not connected yet" : "The Agenda could not load"}
          </div>
          <div className="park-agenda-state-line">
            {state.status === "not-built"
              ? "Pins and your week show here once the Agenda is connected."
              : "Try again in a moment."}
          </div>
        </div>
      </Frame>
    );
  }
  if (state.status === "loading") return <Frame />;
  return (
    <Frame source={state.source}>
      <Ready A={state.data} app={app} api={use} />
    </Frame>
  );
}
