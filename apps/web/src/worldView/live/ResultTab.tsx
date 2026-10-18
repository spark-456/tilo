// TILO-W: Result tab with rich previews, working files accordion, and where it was made
// (design/tilo-w PROMPT.md, Tilo W Parts.dc.html lines 253-365).
import type React from "react";
import { useState } from "react";
import { Icon } from "../../design/tilo-t";
import type { Api } from "../../park/api";
import { openResult, readResult, saveResult } from "../../park/api/results";
import { Markdown } from "../../park/pages/World/markdown";
import type { SharedResult } from "../../park/pages/World/ResultPanel";
import type { RunEvent } from "../../park/pages/World/useRunEvents";
import type { ResultView } from "../../park/pages/World/useRunResult";
import { Markdown } from "../../park/pages/World/markdown";

const readableMath = (text: string): string =>
  text
    .replace(/\$\\to\$/g, "→")
    .replace(/\$([^$\n]+)\$/g, "$1");

function ResultBody({ view, retry }: { view: ResultView; retry?: () => void }) {
  if (view.status === "loading") return <p className="park-world-noruns">Loading the result…</p>;
  if (view.status === "error")
    return (
      <div role="alert">
        <p className="park-world-noruns">The result could not be loaded. Nothing is lost.</p>
        {retry ? (
          <button
            type="button"
            className="park-btn park-btn--secondary park-btn--sm"
            onClick={retry}
          >
            Try again
          </button>
        ) : null}
      </div>
    );
  if (view.status === "file")
    return (
      <p className="park-world-noruns">
        {`The result is a file (${view.blob.type || "unknown type"}). Open or download it to read it.`}
      </p>
    );
  if (view.status !== "text") return null;
  return (
    // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrolling text box must be reachable by keyboard to be read
    <div className="park-world-resulttext" data-testid="result-text" tabIndex={0}>
      {view.kind === "markdown" ? (
        <Markdown text={readableMath(view.text)} />
      ) : (
        <pre className="park-world-resultpre">{readableMath(view.text)}</pre>
      )}
      {view.cut ? (
        <p className="park-world-sub">Showing the start. Download it for the rest.</p>
      ) : null}
    </div>
  );
}

interface DeliveredFile {
  readonly id: string;
  readonly name: string;
  readonly who?: string;
  readonly size?: string;
  readonly color?: string;
}

const FORMAT_NAMES: Record<string, string> = {
  pdf: "Document",
  docx: "Document",
  xlsx: "Spreadsheet",
  csv: "Spreadsheet",
  md: "Notes",
  txt: "Text",
};

function safeDeliverableName(raw: string): string | null {
  const trimmed = raw.trim();
  const cleaned = trimmed.replace(/[^\w\s.-]/g, "").replace(/\s+/g, " ");
  return cleaned || null;
}

function deliveredName(event: RunEvent, id: string): string {
  const data = event.data as
    | { artifact?: { label?: unknown }; format?: unknown; filename?: unknown }
    | undefined;
  if (typeof data?.filename === "string" && data.filename.trim()) {
    const filename = safeDeliverableName(data.filename);
    if (filename) return filename;
  }
  const label = data?.artifact?.label;
  const cleanLabel = typeof label === "string" ? safeDeliverableName(label) : null;
  if (cleanLabel && cleanLabel !== id) return cleanLabel;
  const fromSummary = event.summary.match(
    /^(?:The |Your )?(.+?) (?:is ready|was delivered)(?: in Tilo)?\.?$/i,
  );
  const cleanSummary = fromSummary?.[1] ? safeDeliverableName(fromSummary[1]) : null;
  if (cleanSummary && !/^item$/i.test(cleanSummary)) return cleanSummary;
  const summary = safeDeliverableName(event.summary.replace(/[.!]+$/, ""));
  return (typeof data?.format === "string" && FORMAT_NAMES[data.format]) || summary || "Working file";
}

function extractDeliveredFiles(events: readonly RunEvent[]): DeliveredFile[] {
  const items: DeliveredFile[] = [];
  for (const e of events) {
    const data = e.data as { artifact?: { artifact_id?: unknown } } | undefined;
    const id = data?.artifact?.artifact_id;
    if (
      e.type === "artifact.delivered" &&
      typeof id === "string" &&
      !items.some((x) => x.id === id)
    ) {
      const name = deliveredName(e, id);
      if (!items.some((x) => x.name.toLocaleLowerCase() === name.toLocaleLowerCase()))
        items.push({ id, name });
    }
  }
  return items;
}

export interface ResultTabProps {
  readonly api?: Api;
  readonly worldId: string;
  readonly events?: readonly RunEvent[];
  readonly shared?: SharedResult;
  readonly onOpen?: () => void;
  readonly onDownload?: () => void;
  readonly onShare?: () => void;
}

const DEFAULT_FILES = [
  { name: "venue-shortlist.md", who: "research", color: "ag3", size: "4 KB" },
  { name: "flights-12-options.csv", who: "travel", color: "ag4", size: "9 KB" },
  { name: "casa-do-rio-quote.pdf", who: "research", color: "ag3", size: "210 KB" },
  { name: "budget-draft-v1.xlsx", who: "lead", color: "ag2", size: "18 KB" },
  { name: "agenda-draft.docx", who: "writer", color: "ag5", size: "26 KB" },
  { name: "invite-email.md", who: "writer", color: "ag5", size: "2 KB" },
  { name: "review-notes.md", who: "verifier", color: "ag7", size: "3 KB" },
  { name: "plan-v1.json", who: "director", color: "ag1", size: "6 KB" },
];

function WorkingFiles({
  api,
  worldId,
  items,
}: {
  api?: Api | undefined;
  worldId: string;
  items: readonly DeliveredFile[];
}) {
  const [loadError, setLoadError] = useState(false);
  const readItem = (id: string, use: (b: Blob) => void) => {
    if (!api) return;
    setLoadError(false);
    readResult(api, worldId, id).then(use, () => setLoadError(true));
  };
  return (
    <details data-testid="working-files" className="tw-res-files tw-res-slide-4">
      <summary className="tw-res-files-summary">
        <span className="tw-res-files-summary__icon" aria-hidden="true">
          <Icon name="file" size={18} />
        </span>
        <span className="tw-res-files-summary__text">
          <span className="tw-res-files-summary__title">{`Working files (${items.length})`}</span>
          <span className="tw-res-files-summary__sub">
            {items[0]?.name
              ? `${items[0].name}${items.length > 1 ? ` and ${items.length - 1} more` : ""}`
              : "What the agents made along the way"}
          </span>
        </span>
        <span className="tw-res-files-summary__chev" aria-hidden="true">
          <Icon name="chevD" size={16} />
        </span>
      </summary>

      <ul className="tw-res-files-list">
        {items.map((f) => (
          <li key={f.id} className="tw-res-files__item park-world-resultactions">
            <span className="tw-res-files__dot" data-ag="ag3" />
            <span className="tw-res-files__name park-world-sub">{f.name}</span>
            <button
              type="button"
              className="tw-res-file-btn tw-res-file-btn--icon secondary"
              aria-label={`Open ${f.name}`}
              title={`Open ${f.name}`}
              onClick={() => readItem(f.id, openResult)}
            >
              <Icon name="eye" size={16} />
            </button>
            <button
              type="button"
              className="tw-res-file-btn tw-res-file-btn--icon secondary"
              aria-label={`Download ${f.name}`}
              title={`Download ${f.name}`}
              onClick={() => readItem(f.id, (b) => saveResult(b, f.name))}
            >
              <Icon name="download" size={16} />
            </button>
          </li>
        ))}
      </ul>
      {loadError ? (
        <p className="park-world-noruns" role="alert">
          That item could not be loaded. Nothing is lost.
        </p>
      ) : null}
    </details>
  );
}

export function ResultTab({
  api,
  worldId,
  events = [],
  shared,
  onOpen,
  onDownload,
  onShare,
}: ResultTabProps) {
  const rawDelivered = extractDeliveredFiles(events);
  const view = shared?.view;
  const blob = view && (view.status === "text" || view.status === "file") ? view.blob : null;

  const mainItem = rawDelivered[0];
  const mainName =
    mainItem?.name ??
    (view?.status === "text"
      ? view.text
          .trim()
          .split("\n")[0]
          ?.replace(/^#*\s*/, "") || "Porto offsite plan"
      : "Porto offsite plan");
  const mainEvent = events.find((event) => event.type === "artifact.delivered");
  const mainData = mainEvent?.data as { format?: unknown } | undefined;
  const mainFormat =
    typeof mainData?.format === "string" ? mainData.format.toUpperCase() : "FILE";
  const mainSummary = mainEvent?.summary || "Ready to open or download.";

  const handleOpen = () => {
    if (blob) openResult(blob);
    else if (onOpen) onOpen();
  };

  const handleDownload = () => {
    if (blob) saveResult(blob, mainName);
    else if (onDownload) onDownload();
  };

  const handleShare = () => {
    if (onShare) onShare();
  };

  const lastDeliveryEvent = [...events].reverse().find((e) => e.type === "artifact.delivered");
  const deliveryTime = lastDeliveryEvent
    ? new Date(lastDeliveryEvent.ts)
        .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
        .toLowerCase()
    : "4:16 pm";
  const piecesCount = rawDelivered.length > 0 ? rawDelivered.length : 5;

  return (
    <div className="tw-res-container" data-testid="result-tab">
      {/* 1. Delivered to the Dock Banner */}
      <div className="tw-res-del tw-res-slide-0" data-testid="delivered-banner">
        <span className="tw-res-del__icon" aria-hidden="true">
          <Icon name="parcel" size={18} />
        </span>
        <span className="tw-res-del__meta">
          <span className="tw-res-del__title">Delivered to the Dock</span>
          <span className="tw-res-del__sub">
            artifact.delivered · {deliveryTime} · {piecesCount} pieces
          </span>
        </span>
      </div>

      {/* 2. Main Deliverable Card */}
      <div className="tw-res-card tw-res-card--main tw-res-slide-1" data-testid="run-result">
        <div className="tw-res-hero">
          <div className="tw-res-sheet-mock">
            <span className="tw-res-mock-kicker">TEAM RAO · OFFSITE PLAN</span>
            <span className="tw-res-mock-title">{mainName}</span>
            <span className="tw-res-mock-bar" />
            <span className="tw-res-mock-line tw-res-mock-line--full" />
            <span className="tw-res-mock-line tw-res-mock-line--90" />
            <span className="tw-res-mock-line tw-res-mock-line--80" />
            <div className="tw-res-mock-grid">
              <span className="tw-res-mock-cell" />
              <span className="tw-res-mock-cell" />
              <span className="tw-res-mock-cell" />
              <span className="tw-res-mock-cell" />
            </div>
            <span className="tw-res-mock-line tw-res-mock-line--full" />
            <span className="tw-res-mock-line tw-res-mock-line--70" />
          </div>
          <div className="tw-res-sheet-mock tw-res-sheet-mock--side">
            <span className="tw-res-mock-title">Agenda</span>
            <div className="tw-res-mock-agenda-row">
              <span className="tw-res-mock-day">THU</span>
              <span className="tw-res-mock-line" />
            </div>
            <div className="tw-res-mock-agenda-row">
              <span className="tw-res-mock-day">FRI</span>
              <span className="tw-res-mock-line" />
            </div>
            <div className="tw-res-mock-agenda-row">
              <span className="tw-res-mock-day">SAT</span>
              <span className="tw-res-mock-line" />
            </div>
            <span className="tw-res-mock-box" />
            <span className="tw-res-mock-line tw-res-mock-line--90" />
            <span className="tw-res-mock-line tw-res-mock-line--70" />
          </div>
        </div>

        <div className="tw-res-body">
          <div className="tw-res-meta-line">
            <span className="tw-res-type-pill" data-type={mainFormat}>
              {mainFormat}
            </span>
            <span className="tw-res-meta">Made in Tilo</span>
          </div>

          <h2 className="tw-res-title">{mainName}</h2>
          <p className="tw-res-summary">{mainSummary}</p>

          <div className="tw-res-actions">
            <button type="button" className="tw-res-btn tw-res-btn--pri" onClick={handleOpen}>
              <Icon name="eye" size={16} />
              Open result
            </button>
            <button type="button" className="tw-res-btn tw-res-btn--sec" onClick={handleDownload}>
              <Icon name="download" size={16} />
              Download
            </button>
            <button type="button" className="tw-res-btn tw-res-btn--sec" onClick={handleShare}>
              <Icon name="link" size={16} />
              Share
            </button>
          </div>

          {/* Preserve text view for compatibility with existing tests checking result-text */}
          {view ? (
            <div className="tw-res-compat-body">
              <ResultBody view={view} retry={shared?.retry} />
            </div>
          ) : null}
        </div>
      </div>

      {events.length === 0 ? (
        <>
      {/* 3. ALSO DELIVERED Header */}
      <div className="tw-res-also tw-res-slide-2">ALSO DELIVERED</div>

      {/* Sheet preview */}
      <div className="tw-res-sheet-card tw-res-slide-2">
        <div className="tw-res-card-head">
          <span className="tw-res-type-pill" data-type="XLSX">
            XLSX
          </span>
          <div className="tw-res-card-head__text">
            <span className="tw-res-card-head__title">Offsite budget.xlsx</span>
            <span className="tw-res-card-head__meta">Sheet · 5 lines · made in Tilo by Kai</span>
          </div>
          <button
            type="button"
            className="tw-res-icon-btn"
            aria-label="Download budget"
            onClick={handleDownload}
          >
            <Icon name="download" size={16} />
          </button>
        </div>
        <div className="tw-res-table-wrap">
          <div className="tw-res-table-head">
            <span className="tw-res-cell--center">1</span>
            <span className="tw-res-cell--pad">A · ITEM</span>
            <span className="tw-res-cell--pad">B · DETAIL</span>
            <span className="tw-res-cell--right">C · COST</span>
          </div>
          <div className="tw-res-table-row">
            <span className="tw-res-cell--center tw-res-cell--sunk">2</span>
            <span className="tw-res-cell--pad tw-res-cell--bold">Casa do Rio, 2 nights</span>
            <span className="tw-res-cell--pad tw-res-cell--sub">12 rooms × €168</span>
            <span className="tw-res-cell--right tw-res-cell--mono">€4,032</span>
          </div>
          <div className="tw-res-table-row">
            <span className="tw-res-cell--center tw-res-cell--sunk">3</span>
            <span className="tw-res-cell--pad tw-res-cell--bold">Flights</span>
            <span className="tw-res-cell--pad tw-res-cell--sub">12 people, 3 cities</span>
            <span className="tw-res-cell--right tw-res-cell--mono">€2,140</span>
          </div>
          <div className="tw-res-table-row">
            <span className="tw-res-cell--center tw-res-cell--sunk">4</span>
            <span className="tw-res-cell--pad tw-res-cell--bold">Food and dinners</span>
            <span className="tw-res-cell--pad tw-res-cell--sub">3 days</span>
            <span className="tw-res-cell--right tw-res-cell--mono">€3,960</span>
          </div>
          <div className="tw-res-table-row">
            <span className="tw-res-cell--center tw-res-cell--sunk">5</span>
            <span className="tw-res-cell--pad tw-res-cell--bold">Workshop space</span>
            <span className="tw-res-cell--pad tw-res-cell--sub">Friday</span>
            <span className="tw-res-cell--right tw-res-cell--mono">€1,850</span>
          </div>
          <div className="tw-res-table-row">
            <span className="tw-res-cell--center tw-res-cell--sunk">6</span>
            <span className="tw-res-cell--pad tw-res-cell--bold">
              Local transport and activities
            </span>
            <span className="tw-res-cell--pad tw-res-cell--sub">Boats, trams, tickets</span>
            <span className="tw-res-cell--right tw-res-cell--mono">€2,298</span>
          </div>
          <div className="tw-res-table-total">
            <span className="tw-res-cell--center tw-res-cell--sunk">7</span>
            <span className="tw-res-cell--pad">Total · €1,720 under the €16,000 cap</span>
            <span className="tw-res-cell--right tw-res-cell--mono">€14,280</span>
          </div>
        </div>
      </div>

      {/* Slides preview */}
      <div className="tw-res-slides-card tw-res-slide-3">
        <div className="tw-res-card-head">
          <span className="tw-res-type-pill" data-type="SLIDES">
            SLIDES
          </span>
          <div className="tw-res-card-head__text">
            <span className="tw-res-card-head__title">Kickoff deck</span>
            <span className="tw-res-card-head__meta">8 slides · made in Canva by Pia</span>
          </div>
          <button type="button" className="tw-res-action-btn">
            Open in Canva
          </button>
        </div>
        <div className="tw-res-slides-grid">
          <div className="tw-res-slide-thumb" data-first="true">
            <span className="tw-res-slide-num">01</span>
            <span className="tw-res-slide-title">Porto · 14–16 May</span>
          </div>
          <div className="tw-res-slide-thumb" data-first="false">
            <span className="tw-res-slide-num">02</span>
            <span className="tw-res-slide-title">Why Porto</span>
          </div>
          <div className="tw-res-slide-thumb" data-first="false">
            <span className="tw-res-slide-num">03</span>
            <span className="tw-res-slide-title">Where we stay</span>
          </div>
          <div className="tw-res-slide-thumb" data-first="false">
            <span className="tw-res-slide-num">04</span>
            <span className="tw-res-slide-title">Getting there</span>
          </div>
          <div className="tw-res-slide-badge">+4</div>
        </div>
      </div>

      {/* Web preview */}
      <div className="tw-res-web-card tw-res-slide-3">
        <div className="tw-res-card-head">
          <span className="tw-res-type-pill" data-type="WEB">
            WEB
          </span>
          <div className="tw-res-card-head__text">
            <span className="tw-res-card-head__title">Event site</span>
            <span className="tw-res-card-head__meta">Live · 3 pages · made in Lovable by Pia</span>
          </div>
        </div>
        <div className="tw-res-browser">
          <div className="tw-res-browser-bar">
            <span className="tw-res-browser-dot tw-res-browser-dot--red" />
            <span className="tw-res-browser-dot tw-res-browser-dot--yellow" />
            <span className="tw-res-browser-dot tw-res-browser-dot--green" />
            <span className="tw-res-browser-url">porto-offsite.lovable.app</span>
          </div>
          <div className="tw-res-browser-content">
            <span className="tw-res-web-kicker">TEAM RAO · 14–16 MAY</span>
            <span className="tw-res-web-h1">Porto by the river</span>
            <span className="tw-res-web-sub">Three days, twelve people, one free morning.</span>
            <div className="tw-res-web-days">
              <div className="tw-res-web-day-card">
                <span className="tw-res-web-day-tag">THU 14</span>
                <span className="tw-res-web-day-text">Arrive, river dinner</span>
              </div>
              <div className="tw-res-web-day-card">
                <span className="tw-res-web-day-tag">FRI 15</span>
                <span className="tw-res-web-day-text">Workshop day</span>
              </div>
              <div className="tw-res-web-day-card">
                <span className="tw-res-web-day-tag">SAT 16</span>
                <span className="tw-res-web-day-text">Free morning</span>
              </div>
            </div>
          </div>
        </div>
        <div className="tw-res-web-actions">
          <button type="button" className="tw-res-btn tw-res-btn--pri">
            <Icon name="globe" size={16} />
            Open site
          </button>
          <button type="button" className="tw-res-btn tw-res-btn--sec">
            <Icon name="copy" size={16} />
            Copy link
          </button>
        </div>
      </div>

      {/* Text preview */}
      <div className="tw-res-text-card tw-res-slide-4">
        <div className="tw-res-card-head">
          <span className="tw-res-type-pill" data-type="MD">
            MD
          </span>
          <div className="tw-res-card-head__text">
            <span className="tw-res-card-head__title">Invite email</span>
            <span className="tw-res-card-head__meta">
              Sent from Gmail · 4:11 pm · written by Wren
            </span>
          </div>
        </div>
        <div className="tw-res-text-box">
          <span className="tw-res-text-to">To: 12 people on Team Rao</span>
          <span className="tw-res-text-subj">Porto, 14–16 May: you’re in</span>
          <p className="tw-res-text-p">
            Hi all, we’re off to Porto. Rooms are booked at Casa do Rio and flights are held until
            Friday.
          </p>
          <ul className="tw-res-text-list">
            <li>Thu 14: arrive, dinner by the river at 8</li>
            <li>Fri 15: workshop day</li>
            <li>Sat 16: free morning, flights home after 3 pm</li>
          </ul>
          <p className="tw-res-text-p">Reply with any food needs by Wednesday. M</p>
        </div>
      </div>
        </>
      ) : null}

      {/* 4. Folded Working Files */}
      {rawDelivered.length > 1 ? (
        <WorkingFiles api={api} worldId={worldId} items={rawDelivered.slice(1)} />
      ) : events.length === 0 ? (
        <WorkingFiles
          api={api}
          worldId={worldId}
          items={DEFAULT_FILES.map((f, i) => ({
            id: `def_${i}`,
            name: f.name,
            who: f.who,
            size: f.size,
            color: f.color,
          }))}
        />
      ) : null}

      {/* 5. Where it was made */}
      <div className="tw-res-made tw-res-slide-5" data-testid="where-it-was-made">
        <span className="tw-res-made__header">WHERE IT WAS MADE</span>
        <div className="tw-res-made__grid">
          <div className="tw-res-made__card">
            <span className="tw-res-made__icon" aria-hidden="true">
              <Icon name="sparkle" size={18} />
            </span>
            <span className="tw-res-made__name">Tilo</span>
            <span className="tw-res-made__desc">Plan PDF, budget sheet, invite email</span>
          </div>
        </div>
        <p className="tw-res-made__later">Other services coming later.</p>
      </div>
    </div>
  );
}
